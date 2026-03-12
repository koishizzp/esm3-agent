"""GFP surrogate model utilities.

Keep this package initializer lightweight so dataset-preparation scripts can
import `protein_agent.surrogate.dataset` without pulling in model-only
dependencies such as `joblib` or `xgboost`.
"""
from __future__ import annotations

__all__ = [
    "FeatureConfig",
    "GFPFluorescencePredictor",
    "SequenceFeatureExtractor",
    "load_ensemble_bundle",
    "save_ensemble_bundle",
    "train_ensemble",
]


def __getattr__(name: str):
    if name in {"FeatureConfig", "SequenceFeatureExtractor"}:
        from .features import FeatureConfig, SequenceFeatureExtractor

        mapping = {
            "FeatureConfig": FeatureConfig,
            "SequenceFeatureExtractor": SequenceFeatureExtractor,
        }
        return mapping[name]

    if name in {"load_ensemble_bundle", "save_ensemble_bundle", "train_ensemble"}:
        from .models import load_ensemble_bundle, save_ensemble_bundle, train_ensemble

        mapping = {
            "load_ensemble_bundle": load_ensemble_bundle,
            "save_ensemble_bundle": save_ensemble_bundle,
            "train_ensemble": train_ensemble,
        }
        return mapping[name]

    if name == "GFPFluorescencePredictor":
        from .predictor import GFPFluorescencePredictor

        return GFPFluorescencePredictor

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
