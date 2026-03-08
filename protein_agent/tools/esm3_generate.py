"""Generate sequences via ESM3 model server."""
from __future__ import annotations

from typing import Any

from protein_agent.esm3_integration import ESM3Client

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

    def __init__(self, client: ESM3Client) -> None:
        self.client = client

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.generate(
            prompt=input_data["prompt"],
            num_candidates=input_data.get("num_candidates", 4),
            temperature=input_data.get("temperature", 0.8),
        )
