"""Retrain a GFP surrogate model on the merged active-learning dataset."""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from protein_agent.surrogate.dataset import (
    load_reference_sequence,
    read_table,
    split_dataset,
    write_json,
)
from protein_agent.surrogate.features import FeatureConfig, SequenceFeatureExtractor
from protein_agent.surrogate.models import (
    label_statistics,
    predict_ensemble,
    regression_metrics,
    save_ensemble_bundle,
    train_ensemble,
)


MODEL_PREFIX = "xgb_ensemble_active_v"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-dataset",
        default="data/active_learning/datasets/gfp_active_learning_v001.parquet",
        help="Merged training dataset path",
    )
    parser.add_argument("--reference-fasta", required=True, help="Mature avGFP reference FASTA")
    parser.add_argument(
        "--model-root",
        default="models/gfp_surrogate",
        help="Root directory for surrogate model versions",
    )
    parser.add_argument("--output-dir", default=None, help="Optional explicit model output directory")
    parser.add_argument("--model-name", default=None, help="Optional model version directory name")
    parser.add_argument(
        "--split-column",
        default="split_mutation_count",
        choices=["split_random", "split_mutation_count"],
    )
    parser.add_argument("--model-type", default="xgboost")
    parser.add_argument("--ensemble-size", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--chromophore-start", type=int, default=63)
    parser.add_argument("--chromophore-motif", default="SYG")
    parser.add_argument("--feature-backend", default="hybrid")
    parser.add_argument("--embedding-cache", default=None)
    parser.add_argument("--use-structure-features", action="store_true")
    return parser


def next_model_dir(model_root: str | Path) -> Path:
    root = Path(model_root)
    root.mkdir(parents=True, exist_ok=True)
    highest = 0
    for path in root.iterdir():
        if not path.is_dir():
            continue
        match = re.fullmatch(rf"{re.escape(MODEL_PREFIX)}(\d+)", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return root / f"{MODEL_PREFIX}{highest + 1:03d}"


def resolve_output_dir(args: argparse.Namespace) -> Path:
    if args.output_dir:
        return Path(args.output_dir)
    if args.model_name:
        return Path(args.model_root) / args.model_name
    return next_model_dir(args.model_root)


def resolve_input_dataset(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.exists():
        return candidate
    if candidate.suffix.lower() == ".parquet":
        fallback = candidate.with_suffix(".csv")
        if fallback.exists():
            return fallback
    raise FileNotFoundError(f"Active-learning dataset does not exist: {candidate}")


def train_active_learning_surrogate(args: argparse.Namespace) -> Path:
    dataset_path = resolve_input_dataset(args.input_dataset)

    embedding_cache = None
    if args.embedding_cache:
        embedding_cache = Path(args.embedding_cache).resolve()
        if not embedding_cache.exists():
            raise FileNotFoundError(f"Embedding cache does not exist: {embedding_cache}")
    if args.feature_backend == "hybrid" and embedding_cache is None:
        raise ValueError("feature-backend hybrid requires --embedding-cache")

    df = read_table(dataset_path)
    train_df, valid_df, test_df = split_dataset(df, args.split_column)
    if train_df.empty or valid_df.empty or test_df.empty:
        available = {
            column: sorted(df[column].dropna().astype(str).unique().tolist())
            for column in ("split_random", "split_mutation_count")
            if column in df.columns
        }
        raise ValueError(
            f"Split {args.split_column} produced empty partitions: "
            f"train={len(train_df)}, valid={len(valid_df)}, test={len(test_df)}. "
            f"Available split labels: {available}. "
            "For retrospective active-learning rounds built from initial_base + wetlab, "
            "try --split-column split_random."
        )

    reference_sequence = load_reference_sequence(args.reference_fasta)
    feature_config = FeatureConfig(
        reference_sequence=reference_sequence,
        chromophore_start=args.chromophore_start,
        chromophore_motif=args.chromophore_motif,
        feature_backend=args.feature_backend,
        include_structure_features=args.use_structure_features,
        embedding_cache_path=str(embedding_cache) if embedding_cache is not None else None,
    )
    extractor = SequenceFeatureExtractor(feature_config)

    train_features = extractor.transform_frame(train_df)
    valid_features = extractor.transform_frame(valid_df)
    test_features = extractor.transform_frame(test_df)

    train_labels = train_df["log_fluorescence"].to_numpy(dtype=np.float32)
    valid_labels = valid_df["log_fluorescence"].to_numpy(dtype=np.float32)
    test_labels = test_df["log_fluorescence"].to_numpy(dtype=np.float32)
    sample_weight = train_df["sample_weight"].to_numpy(dtype=np.float32)

    models, training_summary = train_ensemble(
        train_features,
        train_labels,
        features_valid=valid_features,
        labels_valid=valid_labels,
        sample_weight=sample_weight,
        model_type=args.model_type,
        ensemble_size=args.ensemble_size,
        random_seed=args.random_seed,
    )

    prediction_features = test_features if args.model_type == "xgboost" else test_features.toarray()
    test_mean, test_std = predict_ensemble(models, prediction_features)
    evaluation = regression_metrics(test_labels, test_mean)
    evaluation["prediction_std_mean"] = float(test_std.mean()) if len(test_std) else 0.0

    output_dir = resolve_output_dir(args)
    metadata = {
        "model_version": output_dir.name,
        "model_type": args.model_type,
        "split_column": args.split_column,
        "label_column": "log_fluorescence",
        "label_stats": label_statistics(df["log_fluorescence"].to_numpy(dtype=np.float32)),
        "feature_names": extractor.feature_names,
        "feature_backend": args.feature_backend,
        "training_summary": training_summary,
        "evaluation": evaluation,
        "train_rows": int(len(train_df)),
        "valid_rows": int(len(valid_df)),
        "test_rows": int(len(test_df)),
        "training_dataset_path": str(dataset_path),
    }
    save_ensemble_bundle(
        output_dir,
        models=models,
        feature_config=feature_config,
        metadata=metadata,
    )
    write_json(metadata, output_dir / "training_report.json")
    return output_dir


def main() -> None:
    args = build_parser().parse_args()
    output_dir = train_active_learning_surrogate(args)
    print(f"Saved retrained surrogate model to {output_dir}")


if __name__ == "__main__":
    main()
