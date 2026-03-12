"""Prepare Sarkisyan GFP brightness data for surrogate training."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from protein_agent.surrogate.dataset import (
    GFPDatasetConfig,
    build_clean_gfp_dataset,
    dataset_summary,
    load_reference_sequence,
    read_table,
    write_json,
    write_table_with_fallback,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Path to amino_acid_genotypes_to_brightness file")
    parser.add_argument("--reference-fasta", default=None, help="Optional avGFP reference FASTA")
    parser.add_argument(
        "--output-dir",
        default="data/gfp/processed",
        help="Directory for cleaned dataset artifacts",
    )
    parser.add_argument("--reference-name", default="avGFP")
    parser.add_argument("--chromophore-start", type=int, default=63)
    parser.add_argument("--chromophore-motif", default="SYG")
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--train-max-mutations", type=int, default=3)
    parser.add_argument("--valid-max-mutations", type=int, default=4)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    output_dir = Path(args.output_dir)
    reference_sequence = load_reference_sequence(args.reference_fasta)
    config = GFPDatasetConfig(
        reference_sequence=reference_sequence,
        reference_name=args.reference_name,
        chromophore_start=args.chromophore_start,
        chromophore_motif=args.chromophore_motif,
        random_seed=args.random_seed,
        train_max_mutations=args.train_max_mutations,
        valid_max_mutations=args.valid_max_mutations,
    )

    raw_df = read_table(args.input)
    cleaned = build_clean_gfp_dataset(raw_df, config=config)
    cleaned_path = write_table_with_fallback(cleaned, output_dir / "cleaned.parquet")
    write_json(
        {
            "config": {
                "reference_name": config.reference_name,
                "chromophore_start": config.chromophore_start,
                "chromophore_motif": config.chromophore_motif,
                "train_max_mutations": config.train_max_mutations,
                "valid_max_mutations": config.valid_max_mutations,
            },
            "summary": dataset_summary(cleaned),
            "output_path": str(cleaned_path),
        },
        output_dir / "dataset_summary.json",
    )
    print(f"Prepared dataset: {cleaned_path}")
    print(dataset_summary(cleaned))


if __name__ == "__main__":
    main()
