#!/usr/bin/env python3
# coding=utf-8
"""
ESM3 Offline Embedding Pipeline

目标：离线、可复现、可断点续跑的 ESM3 序列嵌入提取流程。
"""

import argparse
import gc
import gzip
import hashlib
import json
import os
import pickle
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import csv
import importlib.util


def _has_torch() -> bool:
    return importlib.util.find_spec("torch") is not None


def _torch_module():
    import torch
    return torch

# 项目根路径
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR if (SCRIPT_DIR / "protein_agent").exists() else Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_runtime_paths() -> tuple[str, str]:
    snapshot_dir = (
        os.environ.get("ESM3_SNAPSHOT_DIR", "").strip()
        or os.environ.get("PROTEIN_AGENT_ESM3_WEIGHTS_DIR", "").strip()
    )
    source_path = (
        os.environ.get("ESM_SOURCE_PATH", "").strip()
        or os.environ.get("PROTEIN_AGENT_ESM3_ROOT", "").strip()
    )

    config_path = REPO_ROOT / "config.py"
    if config_path.exists():
        spec = importlib.util.spec_from_file_location("embedding_runtime_config", config_path)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            snapshot_dir = snapshot_dir or getattr(module, "ESM3_SNAPSHOT_DIR", "")
            source_path = source_path or getattr(module, "ESM_SOURCE_PATH", "")

    return snapshot_dir, source_path


ESM3_SNAPSHOT_DIR, ESM_SOURCE_PATH = _load_runtime_paths()


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def _inject_esm_source_path() -> None:
    if ESM_SOURCE_PATH and ESM_SOURCE_PATH not in sys.path:
        sys.path.insert(0, ESM_SOURCE_PATH)


def _find_local_snapshot() -> Path:
    cache_base = Path(ESM3_SNAPSHOT_DIR)
    preferred = ["main", "offline_snapshot_esm3_sm_open_v1"]

    for snapshot_name in preferred:
        path = cache_base / snapshot_name
        if path.exists():
            return path

    snapshots = sorted([p for p in cache_base.glob("*") if p.is_dir()]) if cache_base.exists() else []
    if snapshots:
        return snapshots[0]

    raise RuntimeError(
        f"找不到ESM3离线snapshot目录: {cache_base}. 请设置 ESM3_SNAPSHOT_DIR。"
    )


def _patch_data_root(local_data_path: Path) -> None:
    from esm.utils.constants import esm3 as C

    @staticmethod
    def patched_data_root(model: str):
        return local_data_path

    C.data_root = patched_data_root


LOCAL_CACHE = None


CANONICAL_AA = set("ACDEFGHIKLMNPQRSTVWY")

def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv_rows(path: Path, rows: List[Dict[str, object]], fieldnames: List[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


@dataclass
class SeqRecord:
    name: str
    sequence: str


class ESM3EmbeddingPipeline:
    def __init__(
        self,
        model_name: str = "esm3_sm_open_v1",
        device: str = "auto",
        max_seq_length: int = 4096,
        half_precision: bool = False,
        pooling: str = "mean",
        l2_normalize: bool = False,
        retry_cpu: bool = False,
    ):
        self.model_name = model_name
        self.max_seq_length = max_seq_length
        self.half_precision = half_precision
        self.pooling = pooling
        self.l2_normalize = l2_normalize
        self.retry_cpu = retry_cpu

        if device == "auto":
            self.device = "cuda" if (_has_torch() and _torch_module().cuda.is_available()) else "cpu"
        else:
            self.device = device

        self.model = None
        self.embedding_config = None
        self.esm_protein_cls = None
        self.stats: Dict[str, int] = {
            "processed": 0,
            "skipped_long": 0,
            "skipped_invalid": 0,
            "failed": 0,
        }

    def load_model(self):
        if self.model is not None:
            return

        global LOCAL_CACHE
        _inject_esm_source_path()
        LOCAL_CACHE = _find_local_snapshot()
        _patch_data_root(LOCAL_CACHE)

        from esm.models.esm3 import ESM3
        from esm.sdk.api import ESMProtein, LogitsConfig
        torch = _torch_module()

        print(f"📦 加载ESM3: {self.model_name}")
        print(f"   设备: {self.device}")
        print(f"   snapshot: {LOCAL_CACHE}")

        self.model = ESM3.from_pretrained(self.model_name)
        self.model = self.model.to(self.device)
        self.embedding_config = LogitsConfig(return_embeddings=True)
        self.esm_protein_cls = ESMProtein

        if self.half_precision and self.device == "cuda":
            self.model = self.model.half()
            print("   ✓ 半精度启用")
        self.model.eval()
        print("   ✓ 模型加载完成")

    def _is_valid_sequence(self, seq: str) -> bool:
        return bool(seq) and set(seq).issubset(CANONICAL_AA)

    def _safe_name(self, raw_name: str) -> str:
        clean = re.sub(r"[^A-Za-z0-9_.-]", "_", raw_name.strip())
        if not clean:
            clean = "sequence"
        return clean

    def _unique_key(self, name: str, sequence: str) -> str:
        digest = hashlib.sha1(sequence.encode("utf-8")).hexdigest()[:10]
        return f"{self._safe_name(name)}_{digest}"

    def _pool_embedding(self, embeddings):
        torch = _torch_module()
        # embeddings shape: [1, L, D]
        if self.pooling == "mean":
            emb = torch.mean(embeddings, dim=-2).squeeze(0)
        elif self.pooling == "bos":
            emb = embeddings[:, 0, :].squeeze(0)
        else:
            raise ValueError(f"不支持的pooling: {self.pooling}")

        if self.l2_normalize:
            emb = torch.nn.functional.normalize(emb, p=2, dim=0)
        return emb

    def embed_sequence(self, sequence: str, try_device: Optional[str] = None) -> np.ndarray:
        use_device = try_device or self.device
        protein = self.esm_protein_cls(sequence=sequence)

        torch = _torch_module()
        with torch.inference_mode():
            protein_tensor = self.model.encode(protein)
            output = self.model.logits(protein_tensor, self.embedding_config)
            emb = self._pool_embedding(output.embeddings)
            return emb.detach().cpu().float().numpy()

    def _iter_fasta(self, input_file: str) -> Iterable[SeqRecord]:
        name = None
        chunks: List[str] = []
        with open(input_file, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith(">"):
                    if name is not None:
                        yield SeqRecord(name=name, sequence="".join(chunks).upper())
                    name = line[1:].split()[0]
                    chunks = []
                else:
                    chunks.append(line)
        if name is not None:
            yield SeqRecord(name=name, sequence="".join(chunks).upper())

    def process_file(
        self,
        input_file: str,
        output_dir: str,
        resume: bool = True,
        save_format: str = "pkl.gz",
        cleanup_freq: int = 10,
        write_per_residue: bool = False,
    ) -> Dict[str, float]:
        self.load_model()

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        embeddings_dir = output_path / "embeddings"
        embeddings_dir.mkdir(parents=True, exist_ok=True)

        metadata_file = output_path / "metadata.csv"
        failed_file = output_path / "failed_sequences.csv"
        run_summary_file = output_path / "run_summary.json"

        done_keys = set()
        if resume and metadata_file.exists():
            try:
                existing = _read_csv_rows(metadata_file)
                done_keys = {str(r.get("unique_key", "")) for r in existing if r.get("unique_key")}
                print(f"↻ 断点续跑: 已完成 {len(done_keys)} 条")
            except Exception:
                done_keys = set()

        records = list(self._iter_fasta(input_file))
        print(f"📖 读取序列: {len(records)} 条")

        metadata_rows: List[Dict[str, object]] = []
        failed_rows: List[Dict[str, str]] = []
        t0 = time.time()

        for idx, rec in enumerate(records, start=1):
            seq = rec.sequence
            unique_key = self._unique_key(rec.name, seq)
            if resume and unique_key in done_keys:
                continue

            if len(seq) > self.max_seq_length:
                self.stats["skipped_long"] += 1
                failed_rows.append({"name": rec.name, "reason": f"too_long:{len(seq)}"})
                continue

            if not self._is_valid_sequence(seq):
                self.stats["skipped_invalid"] += 1
                failed_rows.append({"name": rec.name, "reason": "invalid_residue"})
                continue

            try:
                embedding = self.embed_sequence(seq)
                per_residue_path = ""

                if save_format in ["pkl.gz", "both"]:
                    pkl_file = embeddings_dir / f"{unique_key}_emb.pkl.gz"
                    with gzip.open(pkl_file, "wb") as f:
                        pickle.dump((rec.name, seq, embedding), f)

                if save_format in ["npy", "both"]:
                    npy_file = embeddings_dir / f"{unique_key}_emb.npy"
                    np.save(npy_file, embedding)

                if write_per_residue:
                    torch = _torch_module()
                    with torch.inference_mode():
                        protein_tensor = self.model.encode(self.esm_protein_cls(sequence=seq))
                        output = self.model.logits(protein_tensor, self.embedding_config)
                        residue_emb = output.embeddings.squeeze(0).detach().cpu().float().numpy()
                    residue_path = embeddings_dir / f"{unique_key}_per_residue.npy"
                    np.save(residue_path, residue_emb)
                    per_residue_path = str(residue_path.name)

                metadata_rows.append(
                    {
                        "name": rec.name,
                        "unique_key": unique_key,
                        "length": len(seq),
                        "pooling": self.pooling,
                        "l2_normalized": self.l2_normalize,
                        "embedding_dim": int(embedding.shape[-1]),
                        "per_residue_file": per_residue_path,
                    }
                )
                self.stats["processed"] += 1

            except _torch_module().cuda.OutOfMemoryError:
                _torch_module().cuda.empty_cache()
                if self.retry_cpu and self.device == "cuda":
                    try:
                        self.model = self.model.to("cpu")
                        embedding = self.embed_sequence(seq, try_device="cpu")
                        self.model = self.model.to("cuda")
                        if save_format in ["pkl.gz", "both"]:
                            with gzip.open(embeddings_dir / f"{unique_key}_emb.pkl.gz", "wb") as f:
                                pickle.dump((rec.name, seq, embedding), f)
                        if save_format in ["npy", "both"]:
                            np.save(embeddings_dir / f"{unique_key}_emb.npy", embedding)
                        metadata_rows.append(
                            {
                                "name": rec.name,
                                "unique_key": unique_key,
                                "length": len(seq),
                                "pooling": self.pooling,
                                "l2_normalized": self.l2_normalize,
                                "embedding_dim": int(embedding.shape[-1]),
                                "per_residue_file": "",
                            }
                        )
                        self.stats["processed"] += 1
                    except Exception as e:
                        self.stats["failed"] += 1
                        failed_rows.append({"name": rec.name, "reason": f"oom_retry_failed:{e}"})
                else:
                    self.stats["failed"] += 1
                    failed_rows.append({"name": rec.name, "reason": "oom"})

            except Exception as e:
                self.stats["failed"] += 1
                failed_rows.append({"name": rec.name, "reason": str(e)})

            if idx % cleanup_freq == 0:
                gc.collect()
                if self.device == "cuda":
                    _torch_module().cuda.empty_cache()

        elapsed = time.time() - t0

        if metadata_rows:
            if resume and metadata_file.exists():
                old_rows = _read_csv_rows(metadata_file)
            else:
                old_rows = []
            by_key: Dict[str, Dict[str, object]] = {}
            for row in old_rows + metadata_rows:
                key = str(row.get("unique_key", ""))
                if key:
                    by_key[key] = row
            merged_rows = list(by_key.values())
            _write_csv_rows(
                metadata_file,
                merged_rows,
                fieldnames=["name", "unique_key", "length", "pooling", "l2_normalized", "embedding_dim", "per_residue_file"],
            )

        if failed_rows:
            if resume and failed_file.exists():
                old_failed = _read_csv_rows(failed_file)
            else:
                old_failed = []
            merged_failed = old_failed + failed_rows
            _write_csv_rows(failed_file, merged_failed, fieldnames=["name", "reason"])

        total = sum(self.stats.values())
        summary = {
            "input_file": str(input_file),
            "output_dir": str(output_dir),
            "snapshot": str(LOCAL_CACHE) if LOCAL_CACHE is not None else "unknown",
            "device": self.device,
            "half_precision": self.half_precision,
            "pooling": self.pooling,
            "l2_normalize": self.l2_normalize,
            "max_seq_length": self.max_seq_length,
            "total_seen": total,
            "processed": self.stats["processed"],
            "skipped_long": self.stats["skipped_long"],
            "skipped_invalid": self.stats["skipped_invalid"],
            "failed": self.stats["failed"],
            "elapsed_seconds": elapsed,
            "throughput_seq_per_sec": (self.stats["processed"] / elapsed) if elapsed > 0 else 0,
            "timestamp": int(time.time()),
        }

        with open(run_summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="ESM3离线Embedding Pipeline")
    parser.add_argument("input", help="输入FASTA文件")
    parser.add_argument("-o", "--output", required=True, help="输出目录")
    parser.add_argument("--max-length", type=int, default=4096, help="最大序列长度")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto", help="计算设备")
    parser.add_argument("--half", action="store_true", help="启用半精度")
    parser.add_argument("--pooling", choices=["mean", "bos"], default="mean", help="序列embedding池化策略")
    parser.add_argument("--l2-normalize", action="store_true", help="输出L2归一化embedding")
    parser.add_argument("--format", choices=["pkl.gz", "npy", "both"], default="both", help="输出格式")
    parser.add_argument("--cleanup-freq", type=int, default=10, help="显存/内存清理频率")
    parser.add_argument("--no-resume", action="store_true", help="禁用断点续跑")
    parser.add_argument("--retry-cpu", action="store_true", help="GPU OOM时回退CPU重试")
    parser.add_argument("--per-residue", action="store_true", help="额外输出每残基embedding")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"❌ 输入文件不存在: {args.input}")
        return 1
    if not _has_torch():
        print("❌ 未检测到 torch，请先安装 PyTorch。")
        return 1

    print("=" * 72)
    print("🧬 ESM3 Offline Embedding Pipeline")
    print("=" * 72)
    print(f"input: {args.input}")
    print(f"output: {args.output}")
    print(f"pooling: {args.pooling}")
    print(f"l2_normalize: {args.l2_normalize}")
    print(f"resume: {not args.no_resume}")
    print("=" * 72)

    pipeline = ESM3EmbeddingPipeline(
        device=args.device,
        max_seq_length=args.max_length,
        half_precision=args.half,
        pooling=args.pooling,
        l2_normalize=args.l2_normalize,
        retry_cpu=args.retry_cpu,
    )

    try:
        summary = pipeline.process_file(
            input_file=args.input,
            output_dir=args.output,
            resume=not args.no_resume,
            save_format=args.format,
            cleanup_freq=args.cleanup_freq,
            write_per_residue=args.per_residue,
        )
        print("\n✅ Pipeline完成")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("\n⚠️ 用户中断")
        return 130
    finally:
        if _has_torch() and _torch_module().cuda.is_available():
            _torch_module().cuda.empty_cache()


if __name__ == "__main__":
    sys.exit(main())
