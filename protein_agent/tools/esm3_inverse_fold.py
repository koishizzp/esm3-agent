"""Inverse folding tool via ESM3 model server."""
from __future__ import annotations

from typing import Any

from protein_agent.esm3_integration import ESM3Client

from .base import Tool


class ESM3InverseFoldTool(Tool):
    name = "esm3_inverse_fold"
    description = "Generate sequences conditioned on backbone structure"
    input_schema = {
        "type": "object",
        "properties": {
            "pdb_path": {"type": "string"},
            "pdb_text": {"type": "string"},
            "num_candidates": {"type": "integer", "minimum": 1},
            "temperature": {"type": "number"},
            "num_steps": {"type": "integer", "minimum": 1},
        },
    }

    def __init__(self, client: ESM3Client) -> None:
        self.client = client

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.inverse_fold(
            pdb_path=input_data.get("pdb_path"),
            pdb_text=input_data.get("pdb_text"),
            num_candidates=input_data.get("num_candidates", 4),
            temperature=input_data.get("temperature", 0.8),
            num_steps=input_data.get("num_steps", 1),
        )
