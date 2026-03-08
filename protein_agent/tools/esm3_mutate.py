"""Mutation tool via ESM3 model server."""
from __future__ import annotations

from typing import Any

from protein_agent.esm3_integration import ESM3Client

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

    def __init__(self, client: ESM3Client) -> None:
        self.client = client

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.mutate(
            sequence=input_data["sequence"],
            num_mutations=input_data.get("num_mutations", 3),
            num_candidates=input_data.get("num_candidates", 4),
        )
