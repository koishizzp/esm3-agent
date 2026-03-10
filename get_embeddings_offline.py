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
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR if (SCRIPT_DIR / "protein_agent").exists() else Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_env_file(path: Path) -> Dict[str, str]:
    data: Dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def _runtime_env() -> Dict[str, str]:
    data = _load_env_file(REPO_ROOT / ".env")
    data.update(os.environ)
    return data


MODEL_FILE_NAME = "esm3_sm_open_v1.pth"


def _ensure_repo_root_priority() -> None:
    repo_root_text = str(REPO_ROOT)
    sys.path = [item for item in sys.path if item != repo_root_text]
    sys.path.insert(0, repo_root_text)


def _resolve_runtime_path(path_text: str) -> str:
    text = (path_text or "").strip()
    if not text:
        return ""
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return str(path.resolve(strict=False))


def _normalize_runtime_paths(snapshot_dir: str, source_path: str, data_path: str) -> tuple[str, str, str]:
    snapshot_dir = _resolve_runtime_path(snapshot_dir)
    source_path = _resolve_runtime_path(source_path)
    data_path = _resolve_runtime_path(data_path)

    source_root = Path(source_path) if source_path else None
    weights_dir = Path(snapshot_dir) if snapshot_dir else None

    if not snapshot_dir and source_root is not None:
        candidate = source_root / "weights"
        if candidate.exists():
            snapshot_dir = str(candidate)
            weights_dir = candidate

    if weights_dir is not None and not (weights_dir / MODEL_FILE_NAME).exists():
        candidate = weights_dir / "weights"
        if (candidate / MODEL_FILE_NAME).exists():
            snapshot_dir = str(candidate)

    if not data_path and source_root is not None:
        candidate = source_root / "data"
        if candidate.exists():
            data_path = str(candidate)

    return snapshot_dir, source_path, data_path


def _load_runtime_paths() -> tuple[str, str, str]:
    runtime = _runtime_env()
    snapshot_dir = (
        runtime.get("ESM3_SNAPSHOT_DIR", "").strip()
        or runtime.get("PROTEIN_AGENT_ESM3_WEIGHTS_DIR", "").strip()
    )
    source_path = (
        runtime.get("ESM_SOURCE_PATH", "").strip()
        or runtime.get("PROTEIN_AGENT_ESM3_ROOT", "").strip()
    )
    data_path = (
        runtime.get("LOCAL_DATA_PATH", "").strip()
        or runtime.get("PROTEIN_AGENT_ESM3_DATA_DIR", "").strip()
    )

    config_path = REPO_ROOT / "config.py"
    if config_path.exists():
        spec = importlib.util.spec_from_file_location("embedding_runtime_config", config_path)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            snapshot_dir = snapshot_dir or getattr(module, "ESM3_SNAPSHOT_DIR", "")
            source_path = source_path or getattr(module, "ESM_SOURCE_PATH", "")
            data_path = data_path or getattr(module, "LOCAL_DATA_PATH", "")

    return _normalize_runtime_paths(snapshot_dir, source_path, data_path)


ESM3_SNAPSHOT_DIR, ESM_SOURCE_PATH, LOCAL_DATA_PATH = _load_runtime_paths()
if ESM3_SNAPSHOT_DIR:
    os.environ.setdefault("ESM3_SNAPSHOT_DIR", ESM3_SNAPSHOT_DIR)
if ESM_SOURCE_PATH:
    os.environ.setdefault("ESM_SOURCE_PATH", ESM_SOURCE_PATH)
if LOCAL_DATA_PATH:
    os.environ.setdefault("LOCAL_DATA_PATH", LOCAL_DATA_PATH)


os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")


def _inject_esm_source_path() -> None:
    _ensure_repo_root_priority()
    if not ESM_SOURCE_PATH:
        return
    sys.path = [item for item in sys.path if item != ESM_SOURCE_PATH]
    insert_at = 1 if sys.path and sys.path[0] == str(REPO_ROOT) else 0
    sys.path.insert(insert_at, ESM_SOURCE_PATH)


def _load_direct_model_loader():
    _ensure_repo_root_priority()
    try:
        from protein_agent.esm3_integration.bridge import load_direct_model

        return load_direct_model
    except Exception:
        bridge_path = REPO_ROOT / "protein_agent" / "esm3_integration" / "bridge.py"
        if not bridge_path.exists():
            raise
        spec = importlib.util.spec_from_file_location("protein_agent_local_bridge", bridge_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"failed to load bridge module from {bridge_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "load_direct_model")


def _find_local_data_root() -> Path:
    candidates: List[Path] = []
    if ESM_SOURCE_PATH:
        candidates.append(Path(ESM_SOURCE_PATH))
    if LOCAL_DATA_PATH:
        data_dir = Path(LOCAL_DATA_PATH)
        candidates.append(data_dir.parent if data_dir.name == "data" else data_dir)
    if ESM3_SNAPSHOT_DIR:
        weights_dir = Path(ESM3_SNAPSHOT_DIR)
        candidates.append(weights_dir.parent if weights_dir.name == "weights" else weights_dir)

    seen: set[str] = set()
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        if (resolved / "weights" / MODEL_FILE_NAME).exists():
            return resolved
        if resolved.name == "weights" and (resolved / MODEL_FILE_NAME).exists():
            return resolved.parent
        if resolved.name == "data" and (resolved.parent / "weights" / MODEL_FILE_NAME).exists():
            return resolved.parent
        if (resolved / "data" / "weights" / MODEL_FILE_NAME).exists():
            return resolved

    checked = ", ".join(str(path.resolve(strict=False)) for path in candidates) or "<none>"
    raise RuntimeError(
        "could not infer the ESM3 data root for fallback loading. "
        f"Checked: {checked}. "
        "Set PROTEIN_AGENT_ESM3_ROOT, PROTEIN_AGENT_ESM3_WEIGHTS_DIR, and PROTEIN_AGENT_ESM3_DATA_DIR."
    )


"""

def _find_local_snapshot() -> Path:
    if not ESM3_SNAPSHOT_DIR:
        raise RuntimeError("未配置 ESM3_SNAPSHOT_DIR / PROTEIN_AGENT_ESM3_WEIGHTS_DIR；请先加载 .env。")
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


"""

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
        try:
            from esm.sdk.api import ESMProtein, LogitsConfig
            load_direct_model = _load_direct_model_loader()

            self.model = load_direct_model(
                {
                    "model": self.model_name,
                    "model_name": self.model_name,
                    "source_path": ESM_SOURCE_PATH,
                    "weights_dir": ESM3_SNAPSHOT_DIR,
                    "data_dir": LOCAL_DATA_PATH,
                    "device": self.device,
                }
            )
            LOCAL_CACHE = Path(ESM3_SNAPSHOT_DIR) if ESM3_SNAPSHOT_DIR else None
            print(f"Loading ESM3: {self.model_name}")
            print(f"   device: {self.device}")
            print(f"   snapshot: {LOCAL_CACHE}")
            if LOCAL_DATA_PATH:
                print(f"   data: {LOCAL_DATA_PATH}")
            self.model = self.model.to(self.device)
            self.embedding_config = LogitsConfig(return_embeddings=True)
            self.esm_protein_cls = ESMProtein
            if self.half_precision and self.device == "cuda":
                self.model = self.model.half()
                print("   half precision enabled")
            self.model.eval()
            print("   model ready")
            return
        except Exception as direct_loader_exc:  # noqa: BLE001
            print(f"   direct_loader_fallback: {direct_loader_exc}")
        LOCAL_CACHE = _find_local_data_root()
        _patch_data_root(LOCAL_CACHE)

        from esm.models.esm3 import ESM3
        from esm.sdk.api import ESMProtein, LogitsConfig
        torch = _torch_module()

        print(f"Loading ESM3 via fallback: {self.model_name}")
        print(f"   device: {self.device}")
        print(f"   data_root: {LOCAL_CACHE}")

        print(f"📦 加载ESM3: {self.model_name}")
        print(f"   设备: {self.device}")
        print(f"   snapshot: {LOCAL_CACHE}")

        self.model = ESM3.from_pretrained(self.model_name)
        self.model = self.model.to(self.device)
        self.embedding_config = LogitsConfig(return_embeddings=True)
        self.esm_protein_cls = ESMProtein

        if self.half_precision and self.device == "cuda":
            self.model = self.model.half()
            print("   half precision enabled")
        self.model.eval()
        print("   model ready")
        return
        """

        if self.half_precision and self.device == "cuda":
            self.model = self.model.half()
            print("   ✓ 半精度启用")
        self.model.eval()
        print("   ✓ 模型加载完成")

        """

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


"""

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


"""

def main() -> int:
    parser = argparse.ArgumentParser(description="ESM3 offline embedding pipeline")
    parser.add_argument("input", help="Input FASTA file")
    parser.add_argument("-o", "--output", required=True, help="Output directory")
    parser.add_argument("--max-length", type=int, default=4096, help="Maximum sequence length")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto", help="Compute device")
    parser.add_argument("--half", action="store_true", help="Use half precision")
    parser.add_argument("--pooling", choices=["mean", "bos"], default="mean", help="Pooling strategy")
    parser.add_argument("--l2-normalize", action="store_true", help="L2-normalize output embeddings")
    parser.add_argument("--format", choices=["pkl.gz", "npy", "both"], default="both", help="Output format")
    parser.add_argument("--cleanup-freq", type=int, default=10, help="Cleanup interval")
    parser.add_argument("--no-resume", action="store_true", help="Disable resume mode")
    parser.add_argument("--retry-cpu", action="store_true", help="Retry on CPU after CUDA OOM")
    parser.add_argument("--per-residue", action="store_true", help="Also write per-residue embeddings")

    args = parser.parse_args()
    args.input = str(Path(args.input).resolve())
    args.output = str(Path(args.output).resolve())

    if not os.path.exists(args.input):
        print(f"Input file does not exist: {args.input}")
        return 1
    if not _has_torch():
        print("torch is not installed")
        return 1

    print("=" * 72)
    print("ESM3 Offline Embedding Pipeline")
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
        print("\nPipeline complete")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130
    finally:
        if _has_torch() and _torch_module().cuda.is_available():
            _torch_module().cuda.empty_cache()


if __name__ == "__main__":
    sys.exit(main())
