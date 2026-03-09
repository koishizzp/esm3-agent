"""Run the end-to-end GFP surrogate preparation, embedding, training, and env wiring pipeline."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-input", required=True, help="Figshare amino_acid_genotypes_to_brightness file")
    parser.add_argument("--reference-fasta", required=True, help="avGFP reference FASTA")
    parser.add_argument("--workspace-dir", required=True, help="Workspace root for processed data/models")
    parser.add_argument("--embedding-script", required=True, help="Path to get_embeddings_offline.py")
    parser.add_argument("--esm-python", required=True, help="Python interpreter inside the ESM3 environment")
    parser.add_argument("--env-file", default=None, help="Optional .env file to update")
    parser.add_argument("--model-name", default="xgb_ensemble_v1")
    parser.add_argument("--ensemble-size", type=int, default=5)
    parser.add_argument("--split-column", default="split_mutation_count", choices=["split_random", "split_mutation_count"])
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--pooling", default="mean", choices=["mean", "bos"])
    parser.add_argument("--half", action="store_true")
    parser.add_argument("--l2-normalize", action="store_true")
    return parser


def run_command(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, check=True)


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(updates)
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if "=" not in stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        key, _, _ = stripped.partition("=")
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    if remaining:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# GFP surrogate scoring")
        for key, value in remaining.items():
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main() -> None:
    args = build_parser().parse_args()
    workspace_dir = Path(args.workspace_dir)
    processed_dir = workspace_dir / "data" / "gfp" / "processed"
    embedding_dir = workspace_dir / "data" / "gfp" / "embeddings" / "esm3_mean_v1"
    model_dir = workspace_dir / "models" / "gfp_surrogate" / args.model_name
    embedding_cache = embedding_dir / "embedding_cache.npz"

    python = sys.executable
    run_command(
        [
            python,
            str(Path(__file__).with_name("prepare_gfp_dataset.py")),
            "--input",
            args.raw_input,
            "--reference-fasta",
            args.reference_fasta,
            "--output-dir",
            str(processed_dir),
        ]
    )
    cleaned_dataset = processed_dir / "cleaned.parquet"
    if not cleaned_dataset.exists():
        cleaned_dataset = processed_dir / "cleaned.csv"
    run_command(
        [
            python,
            str(Path(__file__).with_name("extract_gfp_embeddings.py")),
            "--input",
            str(cleaned_dataset),
            "--output-dir",
            str(embedding_dir),
            "--embedding-script",
            args.embedding_script,
            "--python",
            args.esm_python,
            "--device",
            args.device,
            "--pooling",
            args.pooling,
            "--format",
            "both",
        ]
        + (["--half"] if args.half else [])
        + (["--l2-normalize"] if args.l2_normalize else [])
    )
    run_command(
        [
            python,
            str(Path(__file__).with_name("train_gfp_surrogate.py")),
            "--input",
            str(cleaned_dataset),
            "--output-dir",
            str(model_dir),
            "--reference-fasta",
            args.reference_fasta,
            "--split-column",
            args.split_column,
            "--model-type",
            "xgboost",
            "--ensemble-size",
            str(args.ensemble_size),
            "--feature-backend",
            "hybrid",
            "--embedding-cache",
            str(embedding_cache),
        ]
    )

    if args.env_file:
        update_env_file(
            Path(args.env_file),
            {
                "PROTEIN_AGENT_SCORING_BACKEND": "hybrid",
                "PROTEIN_AGENT_SURROGATE_MODEL_PATH": str(model_dir),
                "PROTEIN_AGENT_SURROGATE_MODEL_TYPE": "xgboost",
                "PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE": str(args.ensemble_size),
                "PROTEIN_AGENT_SURROGATE_FEATURE_BACKEND": "hybrid",
                "PROTEIN_AGENT_SURROGATE_USE_STRUCTURE_FEATURES": "false",
            },
        )
        print(f"Updated env file: {args.env_file}")

    print(f"Pipeline complete. Model directory: {model_dir}")


if __name__ == "__main__":
    main()
