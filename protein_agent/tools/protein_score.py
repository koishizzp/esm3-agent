"""Protein scoring utility with heuristic and structure-aware features."""
from __future__ import annotations

from typing import Any

from .base import Tool

HYDROPHOBIC = set("AILMFWVY")
CHARGED = set("KRDE")
FLUOR_HINT = set("GSTY")


class ProteinScoreTool(Tool):
    name = "protein_score"
    description = "Score protein candidates for stability and GFP-like fluorescence potential"
    input_schema = {
        "type": "object",
        "properties": {
            "sequence": {"type": "string"},
            "structure": {"type": "object"},
        },
        "required": ["sequence"],
    }

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        sequence = input_data["sequence"].strip().upper()
        if not sequence:
            raise ValueError("Sequence cannot be empty")
        length = len(sequence)
        hydrophobic_ratio = sum(aa in HYDROPHOBIC for aa in sequence) / length
        charged_ratio = sum(aa in CHARGED for aa in sequence) / length
        fluor_ratio = sum(aa in FLUOR_HINT for aa in sequence) / length

        structure = input_data.get("structure") or {}
        confidence = float(structure.get("confidence", 0.0))

        stability = max(0.0, 1.0 - abs(hydrophobic_ratio - 0.35) * 2.0)
        fluor_component = min(1.0, fluor_ratio * 2.0)
        charge_penalty = max(0.0, charged_ratio - 0.2)
        score = (
            0.40 * stability
            + 0.45 * fluor_component
            + 0.15 * confidence
            - 0.30 * charge_penalty
        )
        return {
            "score": round(score, 6),
            "metrics": {
                "length": length,
                "hydrophobic_ratio": hydrophobic_ratio,
                "charged_ratio": charged_ratio,
                "fluor_ratio": fluor_ratio,
                "structure_confidence": confidence,
                "stability": stability,
                "charge_penalty": charge_penalty,
            },
        }
