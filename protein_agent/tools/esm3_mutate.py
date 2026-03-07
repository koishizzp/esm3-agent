"""Mutation tool via ESM3 model server."""
from __future__ import annotations

from typing import Any
import requests

from .base import Tool


class ESM3MutateTool(Tool):
    name = "esm3_mutate"
    description = "Mutate an existing protein sequence with ESM3 guidance"
    input_schema = {
        "type": "object",
        "properties": {
            "sequence": {"type": "string"},
            "num_mutations": {"type": "integer", "minimum": 1},
            "num_candidates": {"type": "integer", "minimum": 1},
        },
        "required": ["sequence"],
    }

    def __init__(self, server_url: str, timeout: int = 120) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "sequence": input_data["sequence"],
            "num_mutations": input_data.get("num_mutations", 3),
            "num_candidates": input_data.get("num_candidates", 4),
        }
        resp = requests.post(
            f"{self.server_url}/mutate_sequence", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        return resp.json()
