"""Prepare an initial-train / hidden-oracle split for retrospective active learning."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from protein_agent.memory.storage import ensure_active_learning_layout
from protein_agent.surrogate.dataset import read_table, write_json, write_table_with_fallback


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dataset", required=True, help="Cleaned GFP dataset path")
    parser.add_argument(
        "--split-column",
        default="split_mutation_count",
        choices=["split_random", "split_mutation_count"],
        help="Column used to define the retrospective split",
    )
    parser.add_argument(
        "--initial-splits",
        default="train,valid",
        help="Comma-separated split labels used for the initial surrogate dataset",
    )
    parser.add_argument(
        "--oracle-splits",
        default="test",
        help="Comma-separated split labels used as the hidden wet-lab oracle pool",
    )
    parser.add_argument(
        "--output-dir",
        default="data/active_learning/retrospective",
        help="Directory for the generated retrospective split artifacts",
    )
    return parser


def parse_split_list(value: str) -> list[str]:
    return [item.strip() for item in str(value).split(",") if item.strip()]


def main() -> None:
    args = build_parser().parse_args()
    frame = read_table(args.input_dataset)
    if args.split_column not in frame.columns:
        raise KeyError(f"Missing split column {args.split_column} in {args.input_dataset}")

    initial_splits = parse_split_list(args.initial_splits)
    oracle_splits = parse_split_list(args.oracle_splits)
    if not initial_splits:
        raise ValueError("initial-splits cannot be empty")
    if not oracle_splits:
        raise ValueError("oracle-splits cannot be empty")

    initial_df = frame[frame[args.split_column].isin(initial_splits)].reset_index(drop=True)
    oracle_df = frame[frame[args.split_column].isin(oracle_splits)].reset_index(drop=True)
    if initial_df.empty:
        raise ValueError("Initial dataset is empty after applying split filter")
    if oracle_df.empty:
        raise ValueError("Oracle dataset is empty after applying split filter")

    ensure_active_learning_layout()
    output_dir = Path(args.output_dir)
    initial_path = write_table_with_fallback(initial_df, output_dir / "initial_base.parquet")
    oracle_path = write_table_with_fallback(oracle_df, output_dir / "oracle_pool.parquet")
    write_json(
        {
            "input_dataset": str(args.input_dataset),
            "split_column": args.split_column,
            "initial_splits": initial_splits,
            "oracle_splits": oracle_splits,
            "initial_rows": int(len(initial_df)),
            "oracle_rows": int(len(oracle_df)),
            "initial_output": str(initial_path),
            "oracle_output": str(oracle_path),
        },
        output_dir / "split_summary.json",
    )
    print(f"Saved initial dataset to {initial_path}")
    print(f"Saved oracle dataset to {oracle_path}")


if __name__ == "__main__":
    main()
