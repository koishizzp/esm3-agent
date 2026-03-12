"""Simulate wet-lab results by looking up labels from a public oracle dataset."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from protein_agent.memory.storage import ensure_active_learning_layout
from protein_agent.surrogate.dataset import read_table


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-csv", required=True, help="Batch CSV exported for wet-lab")
    parser.add_argument("--oracle-dataset", required=True, help="Dataset containing ground-truth labels")
    parser.add_argument(
        "--label-column",
        default="log_fluorescence",
        help="Ground-truth label column in the oracle dataset",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output CSV path. Defaults to data/active_learning/wetlab/<batch_id>_simulated.csv",
    )
    parser.add_argument(
        "--assay-name",
        default="retrospective_public_oracle",
        help="Assay name written into the simulated result rows",
    )
    parser.add_argument(
        "--assay-date",
        default=None,
        help="Optional assay date override. Defaults to today's date",
    )
    parser.add_argument(
        "--operator",
        default="simulator",
        help="Operator field for the generated mock wet-lab file",
    )
    parser.add_argument(
        "--noise-std",
        type=float,
        default=0.0,
        help="Optional Gaussian noise added to the oracle label for simulation",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Random seed used when --noise-std > 0",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Skip sequences that are not present in the oracle dataset instead of failing",
    )
    return parser


def load_batch_rows(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build_oracle_lookup(dataset_path: str | Path, label_column: str) -> dict[str, dict[str, Any]]:
    frame = read_table(dataset_path)
    if "sequence" not in frame.columns:
        raise KeyError(f"Oracle dataset missing sequence column: {dataset_path}")
    if label_column not in frame.columns:
        raise KeyError(f"Oracle dataset missing label column {label_column}: {dataset_path}")

    deduped = frame.drop_duplicates(subset=["sequence"], keep="last")
    lookup: dict[str, dict[str, Any]] = {}
    for row in deduped.to_dict(orient="records"):
        sequence = str(row.get("sequence") or "").strip().upper()
        if sequence:
            lookup[sequence] = row
    return lookup


def simulate_rows(
    batch_rows: list[dict[str, Any]],
    *,
    oracle_lookup: dict[str, dict[str, Any]],
    label_column: str,
    assay_name: str,
    assay_date: str,
    operator: str,
    noise_std: float,
    seed: int,
    allow_missing: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    rng = np.random.default_rng(seed)
    simulated: list[dict[str, Any]] = []
    missing: list[str] = []

    for row in batch_rows:
        sequence = str(row.get("sequence") or "").strip().upper()
        batch_id = str(row.get("batch_id") or "").strip()
        oracle_row = oracle_lookup.get(sequence)
        if oracle_row is None:
            missing.append(sequence)
            if allow_missing:
                continue
            raise KeyError(f"Sequence not found in oracle dataset: {sequence}")

        measured_value = float(oracle_row[label_column])
        if noise_std > 0:
            measured_value += float(rng.normal(0.0, noise_std))

        simulated.append(
            {
                "batch_id": batch_id,
                "sequence": sequence,
                "measured_log_fluorescence": measured_value,
                "raw_brightness": oracle_row.get("raw_brightness"),
                "label_std": oracle_row.get("label_std", noise_std if noise_std > 0 else 0.0),
                "assay_name": assay_name,
                "assay_date": assay_date,
                "operator": operator,
                "notes": "simulated_from_public_oracle",
            }
        )

    return simulated, missing


def write_simulated_csv(rows: list[dict[str, Any]], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "batch_id",
        "sequence",
        "measured_log_fluorescence",
        "raw_brightness",
        "label_std",
        "assay_name",
        "assay_date",
        "operator",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> None:
    args = build_parser().parse_args()
    batch_rows = load_batch_rows(args.batch_csv)
    if not batch_rows:
        raise ValueError(f"Batch CSV is empty: {args.batch_csv}")

    oracle_lookup = build_oracle_lookup(args.oracle_dataset, args.label_column)
    assay_date = args.assay_date or datetime.utcnow().strftime("%Y-%m-%d")
    simulated_rows, missing = simulate_rows(
        batch_rows,
        oracle_lookup=oracle_lookup,
        label_column=args.label_column,
        assay_name=args.assay_name,
        assay_date=assay_date,
        operator=args.operator,
        noise_std=args.noise_std,
        seed=args.seed,
        allow_missing=args.allow_missing,
    )
    layout = ensure_active_learning_layout()
    batch_id = str(batch_rows[0].get("batch_id") or "simulated_batch").strip() or "simulated_batch"
    output_path = (
        Path(args.output)
        if args.output
        else layout["wetlab"] / f"{batch_id}_simulated.csv"
    )
    saved_path = write_simulated_csv(simulated_rows, output_path)
    print(f"Saved simulated wet-lab CSV: {saved_path}")
    print(f"Resolved sequences: {len(simulated_rows)}")
    print(f"Missing sequences: {len(missing)}")


if __name__ == "__main__":
    main()
