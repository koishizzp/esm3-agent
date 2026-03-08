"""Function-conditioned sequence generation via ESM3 model server."""
from __future__ import annotations

from typing import Any

from protein_agent.esm3_integration import ESM3Client

from .base import Tool


class ESM3FunctionGenerateTool(Tool):
    name = "esm3_function_generate"
    description = "Generate sequences conditioned on function annotations or keywords"
    input_schema = {
        "type": "object",
        "properties": {
            "sequence": {"type": "string"},
            "sequence_length": {"type": "integer", "minimum": 1},
            "function_annotations": {"type": "array"},
            "function_keywords": {"type": "array"},
            "num_candidates": {"type": "integer", "minimum": 1},
            "temperature": {"type": "number"},
            "num_steps": {"type": "integer", "minimum": 1},
        },
    }

    def __init__(self, client: ESM3Client) -> None:
        self.client = client

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.generate_with_function(
            sequence=input_data.get("sequence"),
            sequence_length=input_data.get("sequence_length"),
            function_annotations=input_data.get("function_annotations"),
            function_keywords=input_data.get("function_keywords"),
            num_candidates=input_data.get("num_candidates", 4),
            temperature=input_data.get("temperature", 0.8),
            num_steps=input_data.get("num_steps", 1),
        )
