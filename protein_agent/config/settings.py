"""Centralized configuration for the protein design agent."""
from __future__ import annotations

from functools import lru_cache
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

    esm3_server_url: str = "http://127.0.0.1:8001"
    request_timeout: int = 120

    default_candidates: int = 8
    default_mutations_per_round: int = 4
    default_patience: int = 8
    max_iterations: int = Field(default=100, le=100)

    use_gpu: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
