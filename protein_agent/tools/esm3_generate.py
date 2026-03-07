"""Generate sequences via ESM3 model server."""
from __future__ import annotations

from typing import Any
import requests

from .base import Tool


class ESM3GenerateTool(Tool):
    name = "esm3_generate"
    description = "Generate new candidate protein sequences using ESM3"
    input_schema = {
        "type": "object",
        "properties": {
            "prompt": {"type": "string"},
            "num_candidates": {"type": "integer", "minimum": 1},
            "temperature": {"type": "number"},
        },
        "required": ["prompt"],
    }

    def __init__(self, server_url: str, timeout: int = 120) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "prompt": input_data["prompt"],
            "num_candidates": input_data.get("num_candidates", 4),
            "temperature": input_data.get("temperature", 0.8),
        }
        resp = requests.post(
            f"{self.server_url}/generate_sequence", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()
