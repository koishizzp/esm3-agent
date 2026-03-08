"""Execution layer that routes plan actions to tools."""
from __future__ import annotations

from typing import Any

from protein_agent.config.settings import Settings
from protein_agent.esm3_integration import ESM3Client
from protein_agent.tools.esm3_function_generate import ESM3FunctionGenerateTool
from protein_agent.tools.esm3_generate import ESM3GenerateTool
from protein_agent.tools.esm3_inverse_fold import ESM3InverseFoldTool
from protein_agent.tools.esm3_mutate import ESM3MutateTool
from protein_agent.tools.esm3_structure import ESM3StructureTool
from protein_agent.tools.protein_score import ProteinScoreTool


class ToolExecutor:
    def __init__(self, settings: Settings) -> None:
        self.esm3_client = ESM3Client(settings)
        self.generate_tool = ESM3GenerateTool(self.esm3_client)
        self.mutate_tool = ESM3MutateTool(self.esm3_client)
        self.structure_tool = ESM3StructureTool(self.esm3_client)
        self.inverse_fold_tool = ESM3InverseFoldTool(self.esm3_client)
        self.function_generate_tool = ESM3FunctionGenerateTool(self.esm3_client)
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

    def inverse_fold(
        self,
        pdb_path: str | None = None,
        pdb_text: str | None = None,
        num_candidates: int = 4,
        temperature: float = 0.8,
        num_steps: int = 1,
    ) -> list[str]:
        out = self.inverse_fold_tool.execute(
            {
                "pdb_path": pdb_path,
                "pdb_text": pdb_text,
                "num_candidates": num_candidates,
                "temperature": temperature,
                "num_steps": num_steps,
            }
        )
        return out["sequences"]

    def generate_with_function(
        self,
        sequence: str | None = None,
        sequence_length: int | None = None,
        function_annotations: list[dict[str, Any]] | None = None,
        function_keywords: list[str] | None = None,
        num_candidates: int = 4,
        temperature: float = 0.8,
        num_steps: int = 1,
    ) -> dict[str, Any]:
        return self.function_generate_tool.execute(
            {
                "sequence": sequence,
                "sequence_length": sequence_length,
                "function_annotations": function_annotations,
                "function_keywords": function_keywords,
                "num_candidates": num_candidates,
                "temperature": temperature,
                "num_steps": num_steps,
            }
        )
