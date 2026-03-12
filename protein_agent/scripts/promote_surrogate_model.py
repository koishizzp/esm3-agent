"""Promote a surrogate model version by updating .env and active_model.json."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from protein_agent.memory.storage import ensure_active_learning_layout, read_json, write_json


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, help="Model version directory to activate")
    parser.add_argument("--env-file", default=".env", help="Environment file to update")
    parser.add_argument("--scoring-backend", default="hybrid", help="Scoring backend to keep online")
    parser.add_argument("--ensemble-size", type=int, default=None, help="Optional explicit ensemble size")
    parser.add_argument("--feature-backend", default=None, help="Optional explicit feature backend")
    parser.add_argument(
        "--active-model-path",
        default=None,
        help="Optional active_model.json output path. Defaults to data/active_learning/active_model.json",
    )
    return parser


def update_env_file(env_path: Path, updates: dict[str, str]) -> None:
    existing_lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    remaining = dict(updates)
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if "=" not in stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        key, _, _ = stripped.partition("=")
        if key in remaining:
            new_lines.append(f"{key}={remaining.pop(key)}")
        else:
            new_lines.append(line)

    if remaining:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# Active-learning surrogate")
        for key, value in remaining.items():
            new_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def load_model_bundle_metadata(model_dir: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(model_dir)
    metadata_path = path / "metadata.json"
    feature_path = path / "feature_config.json"
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing metadata.json under {path}")
    if not feature_path.exists():
        raise FileNotFoundError(f"Missing feature_config.json under {path}")
    metadata = read_json(metadata_path)
    feature_config = read_json(feature_path)
    if not isinstance(metadata, dict) or not isinstance(feature_config, dict):
        raise ValueError(f"Invalid model metadata under {path}")
    return metadata, feature_config


def promote_model(
    *,
    model_dir: str | Path,
    env_file: str | Path,
    scoring_backend: str,
    ensemble_size: int | None = None,
    feature_backend: str | None = None,
    active_model_path: str | Path | None = None,
) -> dict[str, Any]:
    model_path = Path(model_dir).resolve()
    metadata, feature_config = load_model_bundle_metadata(model_path)
    layout = ensure_active_learning_layout()
    manifest_path = Path(active_model_path) if active_model_path else layout["active_model"]
    promoted_at = datetime.now(timezone.utc).isoformat()

    resolved_ensemble_size = int(ensemble_size or metadata.get("ensemble_size") or 1)
    resolved_feature_backend = (
        feature_backend
        or str(metadata.get("feature_backend") or feature_config.get("feature_backend") or "mutation")
    )
    resolved_model_type = str(metadata.get("model_type") or "xgboost")
    use_structure_features = bool(feature_config.get("include_structure_features", False))

    update_env_file(
        Path(env_file),
        {
            "PROTEIN_AGENT_SCORING_BACKEND": scoring_backend,
            "PROTEIN_AGENT_SURROGATE_MODEL_PATH": str(model_path),
            "PROTEIN_AGENT_SURROGATE_MODEL_TYPE": resolved_model_type,
            "PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE": str(resolved_ensemble_size),
            "PROTEIN_AGENT_SURROGATE_FEATURE_BACKEND": resolved_feature_backend,
            "PROTEIN_AGENT_SURROGATE_USE_STRUCTURE_FEATURES": str(use_structure_features).lower(),
        },
    )

    manifest = {
        "model_version": str(metadata.get("model_version") or model_path.name),
        "model_path": str(model_path),
        "model_type": resolved_model_type,
        "ensemble_size": resolved_ensemble_size,
        "feature_backend": resolved_feature_backend,
        "use_structure_features": use_structure_features,
        "scoring_backend": scoring_backend,
        "promoted_at": promoted_at,
        "status": "active",
    }
    write_json(manifest, manifest_path)
    return {
        "env_file": str(Path(env_file)),
        "active_model_path": str(manifest_path),
        **manifest,
    }


def main() -> None:
    args = build_parser().parse_args()
    summary = promote_model(
        model_dir=args.model_dir,
        env_file=args.env_file,
        scoring_backend=args.scoring_backend,
        ensemble_size=args.ensemble_size,
        feature_backend=args.feature_backend,
        active_model_path=args.active_model_path,
    )
    print(f"Promoted model {summary['model_version']}")
    print(f"Updated env file: {summary['env_file']}")
    print(f"Active model manifest: {summary['active_model_path']}")


if __name__ == "__main__":
    main()
