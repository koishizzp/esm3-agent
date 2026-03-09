"""Online GFP surrogate predictor."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from protein_agent.config.settings import Settings

from .models import EnsembleBundle, load_ensemble_bundle, predict_ensemble

LOGGER = logging.getLogger(__name__)


class GFPFluorescencePredictor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bundle: EnsembleBundle | None = None
        self._load_error: str | None = None
        self.reload()

    @property
    def available(self) -> bool:
        return self._bundle is not None

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def reload(self) -> None:
        model_path = self.settings.surrogate_model_path
        self._bundle = None
        self._load_error = None
        if not model_path:
            return
        try:
            bundle_path = Path(model_path)
            self._bundle = load_ensemble_bundle(bundle_path)
        except Exception as exc:  # noqa: BLE001
            self._load_error = str(exc)
            LOGGER.warning("Failed to load GFP surrogate model: %s", exc)

    def _normalize_prediction(self, predicted_value: float) -> float:
        metadata = self._bundle.metadata if self._bundle is not None else {}
        label_stats = metadata.get("label_stats") or {}
        lower = float(label_stats.get("q05", label_stats.get("min", 0.0)))
        upper = float(label_stats.get("q95", label_stats.get("max", 1.0)))
        if upper <= lower:
            upper = lower + 1.0
        return max(0.0, min(1.0, (predicted_value - lower) / (upper - lower)))

    def predict(
        self,
        sequence: str,
        structure_metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._bundle is None:
            raise RuntimeError(self._load_error or "Surrogate model is not configured")

        features = self._bundle.feature_extractor.transform(
            [sequence],
            structure_metrics=[structure_metrics or {}],
        )
        model_type = str(self._bundle.metadata.get("model_type") or self.settings.surrogate_model_type)
        fit_features = features if model_type == "xgboost" else features.toarray()
        mean, std = predict_ensemble(self._bundle.models, fit_features)
        predicted_fluorescence = float(mean[0])
        prediction_std = float(std[0])
        surrogate_score = self._normalize_prediction(predicted_fluorescence)
        return {
            "predicted_fluorescence": predicted_fluorescence,
            "prediction_std": prediction_std,
            "surrogate_score": surrogate_score,
            "model_version": str(
                self._bundle.metadata.get("model_version")
                or Path(self.settings.surrogate_model_path or "").name
                or "gfp_surrogate"
            ),
            "model_type": model_type,
            "feature_backend": self._bundle.feature_extractor.config.feature_backend,
        }
