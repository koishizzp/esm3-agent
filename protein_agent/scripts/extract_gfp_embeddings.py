"""Export GFP sequences, run offline ESM3 embedding extraction, and build a cache."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Cleaned dataset path")
    parser.add_argument("--output-dir", required=True, help="Embedding workspace directory")
    parser.add_argument(
        "--embedding-script",
        default="get_embeddings_offline.py",
        help="Path to get_embeddings_offline.py",
    )
    parser.add_argument("--python", default=os.environ.get("PROTEIN_AGENT_ESM3_PYTHON_PATH", sys.executable))
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--pooling", default="mean", choices=["mean", "bos"])
    parser.add_argument("--format", default="both", choices=["pkl.gz", "npy", "both"])
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--l2-normalize", action="store_true")
    parser.add_argument("--retry-cpu", action="store_true")
    parser.add_argument("--cleanup-freq", type=int, default=10)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--sequence-column", default="sequence")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    fasta_path = output_dir / "sequences.fasta"
    cache_path = output_dir / "embedding_cache.npz"

    export_cmd = [
        sys.executable,
        str(Path(__file__).with_name("export_gfp_fasta.py")),
        "--input",
        args.input,
        "--output",
        str(fasta_path),
        "--sequence-column",
        args.sequence_column,
    ]
    subprocess.run(export_cmd, check=True)

    embed_cmd = [
        args.python,
        str(Path(args.embedding_script)),
        str(fasta_path),
        "-o",
        str(output_dir / "offline_run"),
        "--device",
        args.device,
        "--pooling",
        args.pooling,
        "--format",
        args.format,
        "--cleanup-freq",
        str(args.cleanup_freq),
    ]
    if args.half:
        embed_cmd.append("--half")
    if args.l2_normalize:
        embed_cmd.append("--l2-normalize")
    if args.retry_cpu:
        embed_cmd.append("--retry-cpu")
    if args.no_resume:
        embed_cmd.append("--no-resume")
    subprocess.run(embed_cmd, check=True)

    build_cmd = [
        sys.executable,
        str(Path(__file__).with_name("build_embedding_cache.py")),
        "--input-dir",
        str(output_dir / "offline_run"),
        "--output",
        str(cache_path),
    ]
    subprocess.run(build_cmd, check=True)
    print(f"Embedding extraction complete: {cache_path}")


if __name__ == "__main__":
    main()
