"""Export top active-learning candidates to a wet-lab batch CSV."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from protein_agent.active_learning.acquisition import batch_ucb
from protein_agent.active_learning.selection import select_diverse_topk
from protein_agent.memory.experiment_memory import ExperimentMemory, ExperimentRecord
from protein_agent.memory.storage import ensure_active_learning_layout, slugify_filename


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-json", required=True, help="Saved design run JSON path")
    parser.add_argument("--batch-id", default=None, help="Optional batch identifier")
    parser.add_argument("--top-k", type=int, default=24, help="Number of candidates to export")
    parser.add_argument(
        "--acquisition-lambda",
        type=float,
        default=0.5,
        help="Exploration weight applied to prediction_std during ranking",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output CSV path. Defaults to data/active_learning/batches/<batch_id>.csv",
    )
    parser.add_argument(
        "--min-hamming",
        type=int,
        default=0,
        help="Optional minimum Hamming distance between selected sequences",
    )
    return parser


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        item = value.item() if hasattr(value, "item") else value
        return float(item)
    except Exception:  # noqa: BLE001
        return None


def default_batch_id(run_metadata: dict[str, Any]) -> str:
    created_at = str(run_metadata.get("created_at") or "").strip()
    if created_at:
        moment = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    else:
        moment = datetime.now(timezone.utc)
    task_slug = slugify_filename(str(run_metadata.get("task") or "gfp"), default="gfp")
    return f"{task_slug}_{moment.astimezone(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def select_batch_rows(
    memory: ExperimentMemory,
    *,
    batch_id: str,
    top_k: int,
    acquisition_lambda: float,
    min_hamming: int = 0,
) -> list[dict[str, Any]]:
    run_metadata = memory.run_metadata
    active_model_version = str(run_metadata.get("surrogate_model_version") or "").strip() or None
    eligible = [
        record
        for record in memory.all_records()
        if (record.metadata or {}).get("valid_candidate", True) is not False
    ]
    predicted_values = np.asarray(
        [
            _to_float((record.metadata or {}).get("predicted_fluorescence")) or float(record.score)
            for record in eligible
        ],
        dtype=np.float32,
    )
    prediction_stds = np.asarray(
        [
            _to_float((record.metadata or {}).get("prediction_std")) or 0.0
            for record in eligible
        ],
        dtype=np.float32,
    )
    acquisition_scores = batch_ucb(
        predicted_values,
        prediction_stds,
        lambda_=acquisition_lambda,
    )
    selected_pairs = select_diverse_topk(
        [record.sequence for record in eligible],
        acquisition_scores,
        k=top_k,
        min_hamming=min_hamming,
    )
    score_lookup = {sequence: float(score) for sequence, score in selected_pairs}
    record_lookup = {record.sequence: record for record in eligible}

    rows: list[dict[str, Any]] = []
    for index, sequence in enumerate([item[0] for item in selected_pairs], start=1):
        record = record_lookup[sequence]
        metadata = record.metadata or {}
        rows.append(
            {
                "batch_id": batch_id,
                "sequence": record.sequence,
                "score": float(record.score),
                "acquisition_score": score_lookup[record.sequence],
                "surrogate_score": _to_float(metadata.get("surrogate_score")),
                "prediction_std": _to_float(metadata.get("prediction_std")),
                "structure_score": _to_float(metadata.get("structure_score")),
                "model_version": str(metadata.get("model_version") or active_model_version or ""),
                "iteration": int(record.iteration),
                "selected_rank": index,
                "notes": "",
            }
        )
    return rows


def write_batch_csv(rows: list[dict[str, Any]], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "batch_id",
        "sequence",
        "score",
        "acquisition_score",
        "surrogate_score",
        "prediction_std",
        "structure_score",
        "model_version",
        "iteration",
        "selected_rank",
        "notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def main() -> None:
    args = build_parser().parse_args()
    memory = ExperimentMemory.load_json(args.run_json)
    batch_id = args.batch_id or default_batch_id(memory.run_metadata)
    rows = select_batch_rows(
        memory,
        batch_id=batch_id,
        top_k=args.top_k,
        acquisition_lambda=args.acquisition_lambda,
        min_hamming=args.min_hamming,
    )
    layout = ensure_active_learning_layout()
    output_path = Path(args.output) if args.output else layout["batches"] / f"{batch_id}.csv"
    saved_path = write_batch_csv(rows, output_path)
    print(f"Exported {len(rows)} candidates to {saved_path}")


if __name__ == "__main__":
    main()
