"""Score a hidden oracle pool and export a retrospective active-learning batch."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from protein_agent.active_learning.acquisition import batch_ucb
from protein_agent.active_learning.selection import select_diverse_topk
from protein_agent.config.settings import Settings
from protein_agent.memory.storage import ensure_active_learning_layout, slugify_filename
from protein_agent.surrogate.dataset import read_table
from protein_agent.surrogate.predictor import GFPFluorescencePredictor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-dataset", required=True, help="Hidden oracle dataset path")
    parser.add_argument("--batch-id", default=None, help="Optional batch identifier")
    parser.add_argument("--top-k", type=int, default=24, help="Number of candidates to export")
    parser.add_argument("--acquisition-lambda", type=float, default=0.5)
    parser.add_argument("--min-hamming", type=int, default=5)
    parser.add_argument("--model-dir", default=None, help="Optional surrogate model directory override")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output CSV path. Defaults to data/active_learning/batches/<batch_id>.csv",
    )
    return parser


def default_batch_id(dataset_path: str | Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dataset_slug = slugify_filename(Path(dataset_path).stem, default="oracle_pool")
    return f"{dataset_slug}_{stamp}"


def build_predictor(model_dir: str | None = None) -> GFPFluorescencePredictor:
    settings = Settings.from_env()
    if model_dir:
        settings.surrogate_model_path = str(Path(model_dir).resolve())
    predictor = GFPFluorescencePredictor(settings)
    if not predictor.available:
        raise RuntimeError(predictor.load_error or "Surrogate predictor is unavailable")
    return predictor


def score_oracle_pool(
    *,
    oracle_dataset: str | Path,
    predictor: GFPFluorescencePredictor,
    top_k: int,
    acquisition_lambda: float,
    min_hamming: int,
    batch_id: str,
) -> list[dict[str, object]]:
    frame = read_table(oracle_dataset)
    if "sequence" not in frame.columns:
        raise KeyError(f"Oracle dataset missing sequence column: {oracle_dataset}")

    sequences: list[str] = []
    predictions: list[dict[str, float | str]] = []
    seen: set[str] = set()
    for sequence in frame["sequence"].tolist():
        value = str(sequence or "").strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        sequences.append(value)
        predictions.append(predictor.predict(value, structure_metrics={}))

    acquisition_scores = batch_ucb(
        np.asarray([float(item["predicted_fluorescence"]) for item in predictions], dtype=np.float32),
        np.asarray([float(item["prediction_std"]) for item in predictions], dtype=np.float32),
        lambda_=acquisition_lambda,
    )
    selected_pairs = select_diverse_topk(
        sequences,
        acquisition_scores,
        k=top_k,
        min_hamming=min_hamming,
    )
    score_lookup = {sequence: float(score) for sequence, score in selected_pairs}
    prediction_lookup = {sequence: prediction for sequence, prediction in zip(sequences, predictions)}

    rows: list[dict[str, object]] = []
    for rank, sequence in enumerate([item[0] for item in selected_pairs], start=1):
        prediction = prediction_lookup[sequence]
        rows.append(
            {
                "batch_id": batch_id,
                "sequence": sequence,
                "score": float(prediction["surrogate_score"]),
                "acquisition_score": score_lookup[sequence],
                "surrogate_score": float(prediction["surrogate_score"]),
                "prediction_std": float(prediction["prediction_std"]),
                "structure_score": None,
                "model_version": str(prediction["model_version"]),
                "iteration": 0,
                "selected_rank": rank,
                "notes": "retrospective_oracle_batch",
            }
        )
    return rows


def write_batch_csv(rows: list[dict[str, object]], output_path: str | Path) -> Path:
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
    batch_id = args.batch_id or default_batch_id(args.oracle_dataset)
    predictor = build_predictor(args.model_dir)
    rows = score_oracle_pool(
        oracle_dataset=args.oracle_dataset,
        predictor=predictor,
        top_k=args.top_k,
        acquisition_lambda=args.acquisition_lambda,
        min_hamming=args.min_hamming,
        batch_id=batch_id,
    )
    layout = ensure_active_learning_layout()
    output_path = Path(args.output) if args.output else layout["batches"] / f"{batch_id}.csv"
    saved_path = write_batch_csv(rows, output_path)
    print(f"Exported retrospective oracle batch: {saved_path}")
    print(f"Selected candidates: {len(rows)}")


if __name__ == "__main__":
    main()
