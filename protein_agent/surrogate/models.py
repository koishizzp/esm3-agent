"""Model training and persistence for GFP surrogate ensembles."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
from typing import Any

import joblib
import numpy as np
from scipy import sparse
from scipy.stats import pearsonr, spearmanr
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

try:
    from sklearn.metrics import root_mean_squared_error
except Exception:  # noqa: BLE001
    root_mean_squared_error = None

try:
    from xgboost import XGBRegressor
except Exception:  # noqa: BLE001
    XGBRegressor = None

from .features import FeatureConfig, SequenceFeatureExtractor


@dataclass(slots=True)
class EnsembleBundle:
    models: list[Any]
    feature_extractor: SequenceFeatureExtractor
    metadata: dict[str, Any]


def _dense_if_needed(matrix: Any, model_type: str) -> Any:
    if model_type == "xgboost":
        return matrix
    if sparse.issparse(matrix):
        return matrix.toarray()
    return matrix


def _build_model(
    model_type: str,
    random_seed: int,
    extra_params: dict[str, Any] | None = None,
) -> Any:
    params = dict(extra_params or {})
    if model_type == "xgboost" and XGBRegressor is not None:
        base_params = {
            "n_estimators": 300,
            "max_depth": 6,
            "learning_rate": 0.05,
            "subsample": 0.9,
            "colsample_bytree": 0.8,
            "objective": "reg:squarederror",
            "random_state": random_seed,
            "n_jobs": 1,
        }
        base_params.update(params)
        return XGBRegressor(**base_params)

    base_params = {
        "random_state": random_seed,
    }
    base_params.update(params)
    return GradientBoostingRegressor(**base_params)


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    if len(y_true) == 0:
        return {}
    if root_mean_squared_error is not None:
        rmse = float(root_mean_squared_error(y_true, y_pred))
    else:
        try:
            rmse = float(mean_squared_error(y_true, y_pred, squared=False))
        except TypeError:
            rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    metrics: dict[str, float] = {
        "rmse": rmse,
        "mae": float(mean_absolute_error(y_true, y_pred)),
    }
    if len(y_true) > 1:
        metrics["r2"] = float(r2_score(y_true, y_pred))
        metrics["spearman"] = float(spearmanr(y_true, y_pred).statistic)
        metrics["pearson"] = float(pearsonr(y_true, y_pred).statistic)
    return metrics


def label_statistics(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
        "std": float(np.std(values)),
        "q05": float(np.quantile(values, 0.05)),
        "q95": float(np.quantile(values, 0.95)),
    }


def predict_ensemble(models: list[Any], features: Any) -> tuple[np.ndarray, np.ndarray]:
    if not models:
        raise ValueError("No surrogate models loaded")
    predictions = [np.asarray(model.predict(features), dtype=np.float32) for model in models]
    stacked = np.vstack(predictions)
    return stacked.mean(axis=0), stacked.std(axis=0)


def train_ensemble(
    features_train: Any,
    labels_train: np.ndarray,
    *,
    features_valid: Any | None = None,
    labels_valid: np.ndarray | None = None,
    sample_weight: np.ndarray | None = None,
    model_type: str = "xgboost",
    ensemble_size: int = 5,
    random_seed: int = 7,
    model_params: dict[str, Any] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    labels_train = np.asarray(labels_train, dtype=np.float32)
    sample_weight = None if sample_weight is None else np.asarray(sample_weight, dtype=np.float32)

    models: list[Any] = []
    training_runs: list[dict[str, Any]] = []
    fit_train = _dense_if_needed(features_train, model_type=model_type)
    fit_valid = None if features_valid is None else _dense_if_needed(features_valid, model_type=model_type)

    for index in range(ensemble_size):
        seed = random_seed + index
        model = _build_model(model_type=model_type, random_seed=seed, extra_params=model_params)
        fit_kwargs: dict[str, Any] = {}
        if sample_weight is not None:
            fit_kwargs["sample_weight"] = sample_weight
        model.fit(fit_train, labels_train, **fit_kwargs)
        models.append(model)

        run_summary = {"seed": seed}
        train_pred = np.asarray(model.predict(fit_train), dtype=np.float32)
        run_summary["train_metrics"] = regression_metrics(labels_train, train_pred)
        if fit_valid is not None and labels_valid is not None and len(labels_valid):
            valid_pred = np.asarray(model.predict(fit_valid), dtype=np.float32)
            run_summary["valid_metrics"] = regression_metrics(
                np.asarray(labels_valid, dtype=np.float32),
                valid_pred,
            )
        training_runs.append(run_summary)

    return models, {"training_runs": training_runs}


def save_ensemble_bundle(
    output_dir: str | Path,
    *,
    models: list[Any],
    feature_config: FeatureConfig,
    metadata: dict[str, Any],
) -> Path:
    bundle_dir = Path(output_dir)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    for index, model in enumerate(models):
        joblib.dump(model, bundle_dir / f"model_{index}.joblib")

    feature_path = bundle_dir / "feature_config.json"
    feature_path.write_text(json.dumps(feature_config.to_dict(), indent=2), encoding="utf-8")

    metadata_payload = {
        **metadata,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "ensemble_size": len(models),
    }
    (bundle_dir / "metadata.json").write_text(
        json.dumps(metadata_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return bundle_dir


def load_ensemble_bundle(bundle_dir: str | Path) -> EnsembleBundle:
    path = Path(bundle_dir)
    metadata = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    feature_config = FeatureConfig.from_dict(
        json.loads((path / "feature_config.json").read_text(encoding="utf-8"))
    )
    model_paths = sorted(path.glob("model_*.joblib"))
    models = [joblib.load(model_path) for model_path in model_paths]
    return EnsembleBundle(
        models=models,
        feature_extractor=SequenceFeatureExtractor(feature_config),
        metadata=metadata,
    )
