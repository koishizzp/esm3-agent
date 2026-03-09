"""Train a GFP fluorescence surrogate ensemble."""
from __future__ import annotations

import argparse
from pathlib import Path

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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Cleaned dataset path")
    parser.add_argument("--output-dir", required=True, help="Model output directory")
    parser.add_argument("--reference-fasta", default=None, help="Optional avGFP reference FASTA")
    parser.add_argument("--split-column", default="split_mutation_count", choices=["split_random", "split_mutation_count"])
    parser.add_argument("--model-type", default="xgboost")
    parser.add_argument("--ensemble-size", type=int, default=5)
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--chromophore-start", type=int, default=65)
    parser.add_argument("--chromophore-motif", default="SYG")
    parser.add_argument("--feature-backend", default="mutation")
    parser.add_argument("--use-structure-features", action="store_true")
    parser.add_argument("--embedding-cache", default=None)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    df = read_table(args.input)
    train_df, valid_df, test_df = split_dataset(df, args.split_column)
    reference_sequence = load_reference_sequence(args.reference_fasta)
    feature_config = FeatureConfig(
        reference_sequence=reference_sequence,
        chromophore_start=args.chromophore_start,
        chromophore_motif=args.chromophore_motif,
        feature_backend=args.feature_backend,
        include_structure_features=args.use_structure_features,
        embedding_cache_path=args.embedding_cache,
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

    output_dir = Path(args.output_dir)
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
    }
    save_ensemble_bundle(
        output_dir,
        models=models,
        feature_config=feature_config,
        metadata=metadata,
    )
    write_json(metadata, output_dir / "training_report.json")
    print(f"Saved surrogate model to {output_dir}")
    print(evaluation)


if __name__ == "__main__":
    main()
