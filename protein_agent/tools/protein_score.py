"""Protein scoring utility for structure-based proxy scoring."""
from __future__ import annotations

from typing import Any

from protein_agent.config.settings import Settings

from .base import Tool

SCORE_VERSION = "structure_proxy_v3"
HARD_CONSTRAINT_PENALTY = 2.0


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        item = value.item() if hasattr(value, "item") else value
        return float(item)
    except Exception:  # noqa: BLE001
        return None


def _to_float_list(value: Any) -> list[float] | None:
    if value is None:
        return None
    if hasattr(value, "detach"):
        try:
            value = value.detach().cpu().tolist()
        except Exception:  # noqa: BLE001
            return None
    elif hasattr(value, "tolist") and not isinstance(value, (str, bytes, dict)):
        try:
            value = value.tolist()
        except Exception:  # noqa: BLE001
            return None

    if not isinstance(value, (list, tuple)):
        return None

    flattened: list[float] = []

    def collect(item: Any) -> None:
        if isinstance(item, (list, tuple)):
            for child in item:
                collect(child)
            return
        number = _to_float(item)
        if number is not None:
            flattened.append(number)

    collect(value)
    return flattened or None


def _round_metric(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None


def _looks_like_gfp(value: Any) -> bool:
    return isinstance(value, str) and "gfp" in value.strip().lower()


class ProteinScoreTool(Tool):
    name = "protein_score"
    description = "Score protein candidates using structure confidence and optional GFP chromophore constraints"
    input_schema = {
        "type": "object",
        "properties": {
            "sequence": {"type": "string"},
            "structure": {"type": "object"},
            "scoring_context": {"type": "object"},
        },
        "required": ["sequence"],
    }

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _build_scoring_profile(self, input_data: dict[str, Any]) -> dict[str, Any]:
        context = input_data.get("scoring_context")
        if not isinstance(context, dict):
            context = {}

        use_gfp_constraints = context.get("use_gfp_constraints")
        if use_gfp_constraints is None:
            use_gfp_constraints = any(
                _looks_like_gfp(context.get(name))
                for name in ("target", "workflow", "task")
            )
        use_gfp_constraints = bool(use_gfp_constraints)

        require_gfp_chromophore = False
        reference_length = 0
        chromophore_start = 0
        chromophore_motif = ""
        if use_gfp_constraints:
            require_gfp_chromophore = _to_bool(
                context.get("require_gfp_chromophore"),
                self.settings.require_gfp_chromophore,
            )
            reference_length = max(
                0,
                int(context.get("gfp_reference_length") or self.settings.gfp_reference_length or 0),
            )
            chromophore_start = max(
                1,
                int(context.get("gfp_chromophore_start") or self.settings.gfp_chromophore_start or 1),
            )
            chromophore_motif = (
                str(context.get("gfp_chromophore_motif") or self.settings.gfp_chromophore_motif or "SYG")
                .strip()
                .upper()
            ) or "SYG"

        return {
            "use_gfp_constraints": use_gfp_constraints,
            "require_gfp_chromophore": require_gfp_chromophore,
            "reference_length": reference_length,
            "chromophore_start": chromophore_start,
            "chromophore_motif": chromophore_motif,
        }

    def _extract_structure_metrics(self, structure: dict[str, Any]) -> dict[str, Any]:
        raw_confidence = _to_float(structure.get("confidence"))
        ptm = _to_float(structure.get("ptm"))
        iptm = _to_float(structure.get("iptm"))
        mean_plddt = _to_float(structure.get("mean_plddt"))
        per_residue_plddt = _to_float_list(structure.get("per_residue_plddt"))
        mean_plddt_source = "mean_plddt" if mean_plddt is not None else None
        if per_residue_plddt and max(per_residue_plddt) <= 1.0:
            per_residue_plddt = [value * 100.0 for value in per_residue_plddt]

        raw_plddt = structure.get("plddt")
        if per_residue_plddt is None:
            per_residue_plddt = _to_float_list(raw_plddt)
            if per_residue_plddt and max(per_residue_plddt) <= 1.0:
                per_residue_plddt = [value * 100.0 for value in per_residue_plddt]
            if per_residue_plddt:
                mean_plddt_source = "plddt"

        scalar_plddt = _to_float(raw_plddt)
        if mean_plddt is None and scalar_plddt is not None:
            mean_plddt = scalar_plddt if scalar_plddt > 1.0 else scalar_plddt * 100.0
            mean_plddt_source = "plddt"
        elif mean_plddt is not None and mean_plddt <= 1.0:
            mean_plddt *= 100.0

        if mean_plddt is None and per_residue_plddt:
            mean_plddt = sum(per_residue_plddt) / len(per_residue_plddt)
            mean_plddt_source = "per_residue_plddt"

        if mean_plddt is None and raw_confidence is not None:
            mean_plddt = raw_confidence * 100.0 if raw_confidence <= 1.0 else raw_confidence
            mean_plddt_source = "confidence"

        confidence = raw_confidence
        confidence_source = "confidence" if raw_confidence is not None else None
        if confidence is None:
            if mean_plddt is not None:
                confidence = _clip(mean_plddt / 100.0)
                confidence_source = "mean_plddt"
            elif ptm is not None:
                confidence = _clip(ptm)
                confidence_source = "ptm"
            else:
                confidence = 0.0
                confidence_source = "default"

        return {
            "confidence": confidence,
            "confidence_source": confidence_source,
            "mean_plddt": mean_plddt,
            "mean_plddt_source": mean_plddt_source,
            "per_residue_plddt_count": len(per_residue_plddt or []),
            "ptm": ptm,
            "ptm_available": ptm is not None,
            "iptm": iptm,
            "structure_backend": structure.get("backend") or structure.get("entrypoint_used"),
        }

    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        sequence = input_data["sequence"].strip().upper()
        if not sequence:
            raise ValueError("Sequence cannot be empty")
        length = len(sequence)

        structure = input_data.get("structure") or {}
        scoring_profile = self._build_scoring_profile(input_data)
        structure_metrics = self._extract_structure_metrics(structure)

        mean_plddt = structure_metrics["mean_plddt"]
        ptm = structure_metrics["ptm"]
        confidence = structure_metrics["confidence"]
        plddt_norm = _clip((mean_plddt or 0.0) / 100.0) if mean_plddt is not None else _clip(confidence or 0.0)
        ptm_norm = _clip(ptm) if ptm is not None else _clip(confidence or 0.0)
        ptm_component_source = "ptm" if ptm is not None else "confidence_fallback"
        structure_score = 0.70 * plddt_norm + 0.30 * ptm_norm

        use_gfp_constraints = scoring_profile["use_gfp_constraints"]
        motif_start = None
        reference_length = None
        length_delta = None
        required_motif = None
        observed_motif = None
        motif_intact = None
        motif_penalty = 0.0
        length_penalty = 0.0
        valid_candidate = True
        if use_gfp_constraints:
            motif_start = int(scoring_profile["chromophore_start"])
            required_motif = str(scoring_profile["chromophore_motif"])
            motif_end = motif_start - 1 + len(required_motif)
            observed_motif = sequence[motif_start - 1 : motif_end] if len(sequence) >= motif_end else ""
            motif_intact = observed_motif == required_motif
            reference_length = int(scoring_profile["reference_length"])
            length_delta = abs(length - reference_length) if reference_length else 0
            if scoring_profile["require_gfp_chromophore"] and not motif_intact:
                # Hard-constraint penalties must dominate the score range so invalid GFP
                # candidates never outrank valid ones in downstream ranking.
                motif_penalty = HARD_CONSTRAINT_PENALTY
            if reference_length and length_delta:
                length_penalty = min(0.50, length_delta / 10.0)
            valid_candidate = not scoring_profile["require_gfp_chromophore"] or bool(motif_intact)

        score = structure_score - motif_penalty - length_penalty
        score_backend = f"{self.settings.scoring_backend}:{'gfp' if use_gfp_constraints else 'generic'}_structure_proxy"

        score_breakdown = {
            "plddt_norm": round(plddt_norm, 6),
            "ptm_norm": round(ptm_norm, 6),
            "plddt_component": round(0.70 * plddt_norm, 6),
            "ptm_component": round(0.30 * ptm_norm, 6),
            "ptm_component_source": ptm_component_source,
            "structure_score": round(structure_score, 6),
            "motif_penalty": round(motif_penalty, 6),
            "length_penalty": round(length_penalty, 6),
            "final_score": round(score, 6),
        }
        return {
            "score": round(score, 6),
            "valid_candidate": valid_candidate,
            "score_breakdown": score_breakdown,
            "metrics": {
                "length": length,
                "reference_length": reference_length,
                "length_delta": length_delta,
                "motif_start": motif_start,
                "required_motif": required_motif,
                "observed_motif": observed_motif,
                "motif_intact": motif_intact,
                "mean_plddt": _round_metric(mean_plddt),
                "mean_plddt_source": structure_metrics["mean_plddt_source"],
                "ptm": _round_metric(ptm),
                "ptm_available": structure_metrics["ptm_available"],
                "iptm": structure_metrics["iptm"],
                "structure_confidence": _round_metric(confidence),
                "confidence_source": structure_metrics["confidence_source"],
                "plddt_norm": round(plddt_norm, 6),
                "ptm_norm": round(ptm_norm, 6),
                "ptm_component_source": ptm_component_source,
                "structure_score": round(structure_score, 6),
                "motif_penalty": round(motif_penalty, 6),
                "length_penalty": round(length_penalty, 6),
                "score_backend": score_backend,
                "score_version": SCORE_VERSION,
                "structure_backend": structure_metrics["structure_backend"],
                "per_residue_plddt_count": structure_metrics["per_residue_plddt_count"],
                "gfp_constraints_active": use_gfp_constraints,
            },
        }
