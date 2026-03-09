"""Execution layer that routes plan actions to tools."""
from __future__ import annotations

from typing import Any

from protein_agent.config.settings import Settings
from protein_agent.esm3_integration import ESM3Client
from protein_agent.surrogate.predictor import GFPFluorescencePredictor
from protein_agent.tools.esm3_function_generate import ESM3FunctionGenerateTool
from protein_agent.tools.esm3_generate import ESM3GenerateTool
from protein_agent.tools.esm3_inverse_fold import ESM3InverseFoldTool
from protein_agent.tools.esm3_mutate import ESM3MutateTool
from protein_agent.tools.esm3_structure import ESM3StructureTool
from protein_agent.tools.protein_score import ProteinScoreTool


class ToolExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.esm3_client = ESM3Client(settings)
        self.generate_tool = ESM3GenerateTool(self.esm3_client)
        self.mutate_tool = ESM3MutateTool(self.esm3_client)
        self.structure_tool = ESM3StructureTool(self.esm3_client)
        self.inverse_fold_tool = ESM3InverseFoldTool(self.esm3_client)
        self.function_generate_tool = ESM3FunctionGenerateTool(self.esm3_client)
        self.score_tool = ProteinScoreTool(settings)
        self.surrogate_predictor = GFPFluorescencePredictor(settings)

    def _score_mode(self, scoring_context: dict[str, Any] | None) -> str:
        context = scoring_context or {}
        mode = str(context.get("scoring_backend") or self.settings.scoring_backend or "structure").strip().lower()
        if mode not in {"structure", "surrogate", "hybrid"}:
            return "structure"
        return mode

    def _fallback_structure_result(
        self,
        structure_result: dict[str, Any],
        *,
        score_mode: str,
        error: str | None = None,
    ) -> dict[str, Any]:
        metrics = dict(structure_result.get("metrics", {}))
        score_breakdown = dict(structure_result.get("score_breakdown", {}))
        final_mode = "structure" if score_mode == "structure" else "structure_fallback"
        metrics.update(
            {
                "structure_score_backend": metrics.get("score_backend"),
                "structure_score_version": metrics.get("score_version"),
                "score_mode": final_mode,
                "score_backend": final_mode,
                "surrogate_available": False,
                "predicted_fluorescence": None,
                "prediction_std": None,
                "surrogate_score": None,
                "model_version": None,
            }
        )
        if error:
            metrics["surrogate_error"] = error
        score_breakdown["score_mode"] = metrics["score_mode"]
        return {
            **structure_result,
            "metrics": metrics,
            "score_breakdown": score_breakdown,
        }

    def _merge_structure_and_surrogate(
        self,
        structure_result: dict[str, Any],
        surrogate_prediction: dict[str, Any],
        *,
        score_mode: str,
    ) -> dict[str, Any]:
        metrics = dict(structure_result.get("metrics", {}))
        score_breakdown = dict(structure_result.get("score_breakdown", {}))

        structure_component = float(metrics.get("structure_score") or structure_result["score"])
        motif_penalty = float(metrics.get("motif_penalty") or 0.0)
        length_penalty = float(metrics.get("length_penalty") or 0.0)
        penalties = motif_penalty + length_penalty
        surrogate_score = float(surrogate_prediction["surrogate_score"])

        if score_mode == "surrogate":
            final_score = surrogate_score - penalties
            structure_weight = 0.0
            surrogate_weight = 1.0
        else:
            final_score = 0.70 * surrogate_score + 0.30 * structure_component - penalties
            structure_weight = 0.30
            surrogate_weight = 0.70

        metrics.update(
            {
                **surrogate_prediction,
                "score_mode": score_mode,
                "surrogate_available": True,
                "structure_score_backend": metrics.get("score_backend"),
                "structure_score_version": metrics.get("score_version"),
                "score_backend": score_mode,
                "score_version": f"{surrogate_prediction['model_version']}:{score_mode}_v1",
            }
        )
        score_breakdown.update(
            {
                "score_mode": score_mode,
                "structure_component": round(structure_component, 6),
                "structure_weight": round(structure_weight, 6),
                "surrogate_component": round(surrogate_score, 6),
                "surrogate_weight": round(surrogate_weight, 6),
                "final_score": round(final_score, 6),
            }
        )
        return {
            **structure_result,
            "score": round(final_score, 6),
            "metrics": metrics,
            "score_breakdown": score_breakdown,
        }

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

    def evaluate(self, sequence: str, scoring_context: dict[str, Any] | None = None) -> dict[str, Any]:
        structure = self.structure_tool.execute({"sequence": sequence})
        payload = {"sequence": sequence, "structure": structure}
        if scoring_context:
            payload["scoring_context"] = scoring_context
        structure_result = self.score_tool.execute(payload)
        score_mode = self._score_mode(scoring_context)
        if score_mode == "structure":
            return {"structure": structure, **self._fallback_structure_result(structure_result, score_mode=score_mode)}

        if not self.surrogate_predictor.available:
            return {
                "structure": structure,
                **self._fallback_structure_result(
                    structure_result,
                    score_mode=score_mode,
                    error=self.surrogate_predictor.load_error,
                ),
            }

        try:
            surrogate_prediction = self.surrogate_predictor.predict(
                sequence,
                structure_metrics=structure_result.get("metrics", {}),
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "structure": structure,
                **self._fallback_structure_result(
                    structure_result,
                    score_mode=score_mode,
                    error=str(exc),
                ),
            }

        return {
            "structure": structure,
            **self._merge_structure_and_surrogate(
                structure_result,
                surrogate_prediction,
                score_mode=score_mode,
            ),
        }

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
