"""Structure prediction tool via ESM3 model server."""
from __future__ import annotations

from typing import Any

from protein_agent.esm3_integration import ESM3Client

from .base import Tool


class ESM3StructureTool(Tool):
    name = "esm3_structure"
    description = "Predict structure for a protein sequence"
    input_schema = {
        "type": "object",
        "properties": {"sequence": {"type": "string"}},
        "required": ["sequence"],
    }

    def __init__(self, client: ESM3Client) -> None:
        self.client = client

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.predict_structure(sequence=input_data["sequence"])
