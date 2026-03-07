"""Structure prediction tool via ESM3 model server."""
from __future__ import annotations

from typing import Any
import requests

from .base import Tool


class ESM3StructureTool(Tool):
    name = "esm3_structure"
    description = "Predict structure for a protein sequence"
    input_schema = {
        "type": "object",
        "properties": {"sequence": {"type": "string"}},
        "required": ["sequence"],
    }

    def __init__(self, server_url: str, timeout: int = 120) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(
            f"{self.server_url}/predict_structure",
            json={"sequence": input_data["sequence"]},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()
