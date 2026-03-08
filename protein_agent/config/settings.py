"""Centralized configuration for the protein design agent."""
from __future__ import annotations

from functools import lru_cache
import sys
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_prefix="PROTEIN_AGENT_", env_file=".env", extra="ignore")

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
    esm3_model_name: str = "esm3-open"
    esm3_device: str | None = None
    esm3_generate_entrypoint: str | None = None
    esm3_mutate_entrypoint: str | None = None
    esm3_structure_entrypoint: str | None = None
    esm3_extra_pythonpath: str | None = None
    request_timeout: int = 120
    allow_generated_python: bool = False
    generated_python_model: str | None = None
    generated_python_timeout: int = 300

    default_candidates: int = 8
    default_mutations_per_round: int = 4
    default_patience: int = 8
    max_iterations: int = Field(default=100, le=100)

    use_gpu: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
