"""GFP surrogate model utilities."""

from .features import FeatureConfig, SequenceFeatureExtractor
from .models import load_ensemble_bundle, save_ensemble_bundle, train_ensemble

__all__ = [
    "FeatureConfig",
    "GFPFluorescencePredictor",
    "SequenceFeatureExtractor",
    "load_ensemble_bundle",
    "save_ensemble_bundle",
    "train_ensemble",
]


def __getattr__(name: str):
    if name == "GFPFluorescencePredictor":
        from .predictor import GFPFluorescencePredictor

        return GFPFluorescencePredictor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
