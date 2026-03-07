"""Execution layer that routes plan actions to tools."""
from __future__ import annotations

from typing import Any

from protein_agent.config.settings import Settings
from protein_agent.tools.esm3_generate import ESM3GenerateTool
from protein_agent.tools.esm3_mutate import ESM3MutateTool
from protein_agent.tools.esm3_structure import ESM3StructureTool
from protein_agent.tools.protein_score import ProteinScoreTool


class ToolExecutor:
    def __init__(self, settings: Settings) -> None:
        self.generate_tool = ESM3GenerateTool(settings.esm3_server_url, settings.request_timeout)
        self.mutate_tool = ESM3MutateTool(settings.esm3_server_url, settings.request_timeout)
        self.structure_tool = ESM3StructureTool(settings.esm3_server_url, settings.request_timeout)
        self.score_tool = ProteinScoreTool()

    def generate(self, prompt: str, num_candidates: int) -> list[str]:
        out = self.generate_tool.execute({"prompt": prompt, "num_candidates": num_candidates})
        return out["sequences"]

    def mutate(self, sequence: str, num_mutations: int, num_candidates: int) -> list[str]:
        out = self.mutate_tool.execute(
            {
                "sequence": sequence,
                "num_mutations": num_mutations,
                "num_candidates": num_candidates,
            }
        )
        return out["sequences"]

    def evaluate(self, sequence: str) -> dict[str, Any]:
        structure = self.structure_tool.execute({"sequence": sequence})
        score = self.score_tool.execute({"sequence": sequence, "structure": structure})
        return {"structure": structure, **score}
