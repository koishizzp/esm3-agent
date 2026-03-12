"""Build a merged training dataset from base GFP data and wet-lab labels."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pandas as pd

from protein_agent.memory.storage import ensure_active_learning_layout, read_jsonl
from protein_agent.surrogate.dataset import (
    AA_ALPHABET,
    canonical_mutations,
    load_reference_sequence,
    motif_intact,
    read_table,
    write_json,
    write_table_with_fallback,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-dataset",
        default="data/gfp/processed/cleaned.parquet",
        help="Processed base GFP dataset path",
    )
    parser.add_argument("--reference-fasta", required=True, help="Mature avGFP reference FASTA")
    parser.add_argument(
        "--wetlab-dir",
        default=None,
        help="Directory containing normalized wet-lab JSONL files. Defaults to data/active_learning/wetlab",
    )
    parser.add_argument(
        "--wetlab-file",
        action="append",
        default=[],
        help="Optional explicit wet-lab JSONL file. Can be passed multiple times",
    )
    parser.add_argument(
        "--output",
        default="data/active_learning/datasets/gfp_active_learning_v001.parquet",
        help="Merged dataset output path",
    )
    parser.add_argument("--reference-name", default="avGFP")
    parser.add_argument("--chromophore-start", type=int, default=63)
    parser.add_argument("--chromophore-motif", default="SYG")
    return parser


def resolve_base_dataset(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.exists():
        return candidate
    if candidate.suffix.lower() == ".parquet":
        fallback = candidate.with_suffix(".csv")
        if fallback.exists():
            return fallback
    raise FileNotFoundError(f"Base dataset does not exist: {candidate}")


def load_wetlab_records(
    *,
    wetlab_dir: str | Path | None,
    wetlab_files: list[str],
) -> list[dict[str, Any]]:
    paths: list[Path] = []
    if wetlab_files:
        paths.extend(Path(item) for item in wetlab_files)
    else:
        layout = ensure_active_learning_layout()
        base_dir = Path(wetlab_dir) if wetlab_dir else layout["wetlab"]
        paths.extend(sorted(base_dir.glob("*.jsonl")))

    records: list[dict[str, Any]] = []
    for path in paths:
        records.extend(read_jsonl(path))
    return records


def wetlab_records_to_frame(
    rows: list[dict[str, Any]],
    *,
    reference_sequence: str,
    reference_name: str,
    chromophore_start: int,
    chromophore_motif: str,
) -> pd.DataFrame:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        sequence = str(row.get("sequence") or "").strip().upper()
        if not sequence:
            continue
        if len(sequence) != len(reference_sequence):
            continue
        if any(residue not in AA_ALPHABET for residue in sequence):
            continue
        mutations = canonical_mutations(sequence, reference_sequence)
        normalized.append(
            {
                "sequence": sequence,
                "mutations": " ".join(mutations),
                "num_mutations": len(mutations),
                "log_fluorescence": float(row["measured_log_fluorescence"]),
                "label_std": float(row.get("label_std") or 0.0),
                "sample_weight": max(float(row.get("sample_weight") or 1.0), 1.0),
                "motif_intact": motif_intact(sequence, chromophore_start, chromophore_motif),
                "reference_name": reference_name,
                "source": "wetlab",
                "batch_id": str(row.get("batch_id") or "").strip(),
                "assay_date": str(row.get("assay_date") or "").strip(),
                "assay_name": str(row.get("assay_name") or "").strip(),
                "operator": str(row.get("operator") or "").strip(),
                "notes": str(row.get("notes") or "").strip(),
                "raw_brightness": row.get("raw_brightness"),
                "imported_at": str(row.get("imported_at") or "").strip(),
                "split_random": "train",
                "split_mutation_count": "train",
            }
        )
    return pd.DataFrame.from_records(normalized)


def merge_active_learning_dataset(base_df: pd.DataFrame, wetlab_df: pd.DataFrame) -> pd.DataFrame:
    base = base_df.copy()
    if base.empty and wetlab_df.empty:
        return pd.DataFrame()

    for column, default in {
        "source": "base_public",
        "batch_id": "",
        "assay_date": "",
        "assay_name": "",
        "operator": "",
        "notes": "",
        "raw_brightness": None,
        "imported_at": "",
    }.items():
        if column not in base.columns:
            base[column] = default

    if "split_random" not in base.columns:
        base["split_random"] = "train"
    if "split_mutation_count" not in base.columns:
        base["split_mutation_count"] = "train"

    base["source_priority"] = 0
    wetlab = wetlab_df.copy()
    if wetlab.empty:
        merged = base
    else:
        wetlab["source_priority"] = 1
        merged = pd.concat([base, wetlab], ignore_index=True, sort=False)

    merged["assay_sort_key"] = pd.to_datetime(merged["assay_date"], errors="coerce")
    merged["import_sort_key"] = pd.to_datetime(merged["imported_at"], errors="coerce")
    merged = merged.sort_values(
        by=["sequence", "source_priority", "assay_sort_key", "import_sort_key"],
        ascending=[True, True, True, True],
        na_position="first",
    )
    merged = merged.groupby("sequence", as_index=False).tail(1).reset_index(drop=True)
    merged = merged.drop(columns=["source_priority", "assay_sort_key", "import_sort_key"], errors="ignore")
    return merged


def dataset_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"num_rows": 0, "num_sequences": 0, "wetlab_rows": 0}
    return {
        "num_rows": int(len(frame)),
        "num_sequences": int(frame["sequence"].nunique()),
        "wetlab_rows": int((frame["source"] == "wetlab").sum()) if "source" in frame.columns else 0,
        "base_rows": int((frame["source"] == "base_public").sum()) if "source" in frame.columns else 0,
        "label_min": float(frame["log_fluorescence"].min()),
        "label_max": float(frame["log_fluorescence"].max()),
    }


def main() -> None:
    args = build_parser().parse_args()
    base_dataset_path = resolve_base_dataset(args.base_dataset)
    base_df = read_table(base_dataset_path)
    reference_sequence = load_reference_sequence(args.reference_fasta)
    wetlab_records = load_wetlab_records(
        wetlab_dir=args.wetlab_dir,
        wetlab_files=args.wetlab_file,
    )
    wetlab_df = wetlab_records_to_frame(
        wetlab_records,
        reference_sequence=reference_sequence,
        reference_name=args.reference_name,
        chromophore_start=args.chromophore_start,
        chromophore_motif=args.chromophore_motif,
    )
    merged = merge_active_learning_dataset(base_df, wetlab_df)
    output_path = write_table_with_fallback(merged, args.output)
    summary = {
        "base_dataset": str(base_dataset_path),
        "wetlab_records": len(wetlab_records),
        "output_path": str(output_path),
        "summary": dataset_summary(merged),
    }
    write_json(summary, Path(output_path).with_suffix(".summary.json"))
    print(f"Saved merged active-learning dataset to {output_path}")
    print(summary["summary"])


if __name__ == "__main__":
    main()
