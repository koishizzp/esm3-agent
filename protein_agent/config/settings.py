"""Centralized configuration for the protein design agent."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path
import sys


def _load_env_file(path: str = ".env") -> dict[str, str]:
    env: dict[str, str] = {}
    file_path = Path(path)
    if not file_path.exists():
        return env

    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        env[key] = value
    return env


def _env_source() -> dict[str, str]:
    data = _load_env_file()
    data.update(os.environ)
    return data


def _env_get(data: dict[str, str], name: str, default: str | None = None) -> str | None:
    return data.get(name, default)


def _env_get_first(data: dict[str, str], names: list[str], default: str | None = None) -> str | None:
    for name in names:
        if name in data:
            return data[name]
    return default


def _to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _to_int(value: str | None, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _to_optional_str(value: str | None, default: str | None = None) -> str | None:
    if value is None:
        return default
    value = value.strip()
    return value if value else None


@dataclass(slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_name: str = "ESM3 Protein Agent"
    log_level: str = "INFO"

    llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None
    openai_base_url: str | None = None

    esm3_backend: str = "auto"
    esm3_server_url: str | None = "http://127.0.0.1:8001"
    esm3_server_api_key: str | None = None
    esm3_server_headers_json: str | None = None
    esm3_python_path: str = sys.executable or "python"
    esm3_root: str | None = None
    esm3_project_dir: str | None = None
    esm3_weights_dir: str | None = None
    esm3_data_dir: str | None = None
    esm3_model_name: str = "esm3_sm_open_v1"
    esm3_device: str | None = None
    esm3_generate_entrypoint: str | None = None
    esm3_mutate_entrypoint: str | None = None
    esm3_structure_entrypoint: str | None = None
    esm3_inverse_fold_entrypoint: str | None = None
    esm3_function_generate_entrypoint: str | None = None
    esm3_extra_pythonpath: str | None = None
    request_timeout: int = 120
    allow_generated_python: bool = False
    generated_python_model: str | None = None
    generated_python_timeout: int = 300

    default_candidates: int = 8
    default_mutations_per_round: int = 4
    default_patience: int = 8
    max_iterations: int = 100

    use_gpu: bool = True
    scoring_backend: str = "structure"
    require_gfp_chromophore: bool = True
    gfp_reference_length: int = 238
    gfp_chromophore_start: int = 65
    gfp_chromophore_motif: str = "SYG"
    use_rosetta: bool = False
    rosetta_topn: int = 5

    @classmethod
    def from_env(cls) -> "Settings":
        data = _env_source()
        defaults = cls()
        max_iterations = min(_to_int(_env_get(data, "PROTEIN_AGENT_MAX_ITERATIONS"), defaults.max_iterations), 100)
        return cls(
            app_name=_env_get(data, "PROTEIN_AGENT_APP_NAME", defaults.app_name) or defaults.app_name,
            log_level=_env_get(data, "PROTEIN_AGENT_LOG_LEVEL", defaults.log_level) or defaults.log_level,
            llm_model=_env_get_first(data, ["PROTEIN_AGENT_LLM_MODEL", "OPENAI_MODEL"], defaults.llm_model)
            or defaults.llm_model,
            openai_api_key=_to_optional_str(_env_get_first(data, ["PROTEIN_AGENT_OPENAI_API_KEY", "OPENAI_API_KEY"])),
            openai_base_url=_to_optional_str(_env_get_first(data, ["PROTEIN_AGENT_OPENAI_BASE_URL", "OPENAI_BASE_URL"])),
            esm3_backend=_env_get(data, "PROTEIN_AGENT_ESM3_BACKEND", defaults.esm3_backend) or defaults.esm3_backend,
            esm3_server_url=_to_optional_str(
                _env_get(data, "PROTEIN_AGENT_ESM3_SERVER_URL"), defaults.esm3_server_url
            ),
            esm3_server_api_key=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_SERVER_API_KEY")),
            esm3_server_headers_json=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_SERVER_HEADERS_JSON")),
            esm3_python_path=_env_get(data, "PROTEIN_AGENT_ESM3_PYTHON_PATH", defaults.esm3_python_path)
            or defaults.esm3_python_path,
            esm3_root=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_ROOT")),
            esm3_project_dir=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_PROJECT_DIR")),
            esm3_weights_dir=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_WEIGHTS_DIR")),
            esm3_data_dir=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_DATA_DIR")),
            esm3_model_name=_env_get(data, "PROTEIN_AGENT_ESM3_MODEL_NAME", defaults.esm3_model_name)
            or defaults.esm3_model_name,
            esm3_device=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_DEVICE")),
            esm3_generate_entrypoint=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_GENERATE_ENTRYPOINT")),
            esm3_mutate_entrypoint=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_MUTATE_ENTRYPOINT")),
            esm3_structure_entrypoint=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_STRUCTURE_ENTRYPOINT")),
            esm3_inverse_fold_entrypoint=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_INVERSE_FOLD_ENTRYPOINT")),
            esm3_function_generate_entrypoint=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_FUNCTION_GENERATE_ENTRYPOINT")),
            esm3_extra_pythonpath=_to_optional_str(_env_get(data, "PROTEIN_AGENT_ESM3_EXTRA_PYTHONPATH")),
            request_timeout=_to_int(_env_get(data, "PROTEIN_AGENT_REQUEST_TIMEOUT"), defaults.request_timeout),
            allow_generated_python=_to_bool(
                _env_get(data, "PROTEIN_AGENT_ALLOW_GENERATED_PYTHON"), defaults.allow_generated_python
            ),
            generated_python_model=_to_optional_str(_env_get(data, "PROTEIN_AGENT_GENERATED_PYTHON_MODEL")),
            generated_python_timeout=_to_int(
                _env_get(data, "PROTEIN_AGENT_GENERATED_PYTHON_TIMEOUT"), defaults.generated_python_timeout
            ),
            default_candidates=_to_int(
                _env_get(data, "PROTEIN_AGENT_DEFAULT_CANDIDATES"), defaults.default_candidates
            ),
            default_mutations_per_round=_to_int(
                _env_get(data, "PROTEIN_AGENT_DEFAULT_MUTATIONS_PER_ROUND"), defaults.default_mutations_per_round
            ),
            default_patience=_to_int(
                _env_get(data, "PROTEIN_AGENT_DEFAULT_PATIENCE"), defaults.default_patience
            ),
            max_iterations=max_iterations,
            use_gpu=_to_bool(_env_get(data, "PROTEIN_AGENT_USE_GPU"), defaults.use_gpu),
            scoring_backend=_env_get(data, "PROTEIN_AGENT_SCORING_BACKEND", defaults.scoring_backend)
            or defaults.scoring_backend,
            require_gfp_chromophore=_to_bool(
                _env_get(data, "PROTEIN_AGENT_REQUIRE_GFP_CHROMOPHORE"), defaults.require_gfp_chromophore
            ),
            gfp_reference_length=_to_int(
                _env_get(data, "PROTEIN_AGENT_GFP_REFERENCE_LENGTH"), defaults.gfp_reference_length
            ),
            gfp_chromophore_start=_to_int(
                _env_get(data, "PROTEIN_AGENT_GFP_CHROMOPHORE_START"), defaults.gfp_chromophore_start
            ),
            gfp_chromophore_motif=_env_get(
                data, "PROTEIN_AGENT_GFP_CHROMOPHORE_MOTIF", defaults.gfp_chromophore_motif
            )
            or defaults.gfp_chromophore_motif,
            use_rosetta=_to_bool(_env_get(data, "PROTEIN_AGENT_USE_ROSETTA"), defaults.use_rosetta),
            rosetta_topn=_to_int(_env_get(data, "PROTEIN_AGENT_ROSETTA_TOPN"), defaults.rosetta_topn),
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings.from_env()
