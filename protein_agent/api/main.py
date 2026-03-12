"""REST API for autonomous protein design."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import logging
from pathlib import Path
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
import requests

from protein_agent.agent.executor import ToolExecutor
from protein_agent.agent.planner import LLMPlanner
from protein_agent.agent.reasoner import ResultReasoner
from protein_agent.agent.workflow import ExperimentLoopEngine
from protein_agent.config.settings import get_settings
from protein_agent.constraints import merge_fixed_residues
from protein_agent.memory.experiment_memory import ExperimentMemory
from protein_agent.memory.storage import ensure_active_learning_layout, timestamped_run_path
from protein_agent.workflows.gfp_optimizer import GFPOptimizer

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)
app = FastAPI(title="Autonomous Protein Design Agent", version="1.0.0")

AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")
INLINE_AA_SEQUENCE_PATTERN = re.compile(
    r"(?<![A-Za-z])([ACDEFGHIKLMNPQRSTVWY]{30,})(?![A-Za-z])",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def load_chat_ui() -> str:
    path = Path(__file__).with_name("chat_ui.html")
    return path.read_text(encoding="utf-8")


class InverseFoldRequest(BaseModel):
    pdb_path: str | None = None
    pdb_text: str | None = None
    num_candidates: int = Field(default=4, ge=1, le=64)
    temperature: float = Field(default=0.8, gt=0)
    num_steps: int = Field(default=1, ge=1, le=512)


class FunctionAnnotationInput(BaseModel):
    label: str
    start: int | None = Field(default=None, ge=1)
    end: int | None = Field(default=None, ge=1)


class FixedResidueInput(BaseModel):
    position: int = Field(..., ge=1)
    residue: str = Field(..., min_length=1, max_length=1)


class DesignRequest(BaseModel):
    task: str = Field(..., description="Natural language protein engineering request")
    max_iterations: int | None = Field(default=None, ge=1, le=100)
    candidates_per_round: int | None = Field(default=None, ge=1, le=64)
    patience: int | None = Field(default=None, ge=1, le=100)
    population_size: int | None = Field(default=None, ge=1, le=512)
    elite_size: int | None = Field(default=None, ge=1, le=128)
    parent_pool_size: int | None = Field(default=None, ge=1, le=256)
    mutations_per_parent: int | None = Field(default=None, ge=1, le=64)
    sequence: str | None = None
    sequence_length: int | None = Field(default=None, ge=1, le=4096)
    pdb_path: str | None = None
    pdb_text: str | None = None
    function_annotations: list[FunctionAnnotationInput] | None = None
    function_keywords: list[str] | None = None
    fixed_residues: list[FixedResidueInput] | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatReasoningRequest(BaseModel):
    message: str = Field(..., description="Natural-language follow-up question")
    conversation: list[ChatMessage] = Field(default_factory=list)
    latest_result: dict[str, Any] | None = None
    current_mode: str = "design"
    previous_best_sequence: str | None = None


def _normalize_amino_acid_sequence(value: str | None) -> str | None:
    cleaned = re.sub(r"\s+", "", str(value or "")).strip().upper()
    if not cleaned:
        return None
    if set(cleaned) - AA_ALPHABET:
        return None
    return cleaned


def _extract_inline_sequence(task: str | None) -> str | None:
    text = str(task or "")
    matches = [
        _normalize_amino_acid_sequence(match.group(1))
        for match in INLINE_AA_SEQUENCE_PATTERN.finditer(text)
    ]
    valid = [item for item in matches if item]
    if not valid:
        return None
    return max(valid, key=len)


def _strip_inline_sequence(task: str, sequence: str | None) -> str:
    if not sequence:
        return task
    cleaned = re.sub(re.escape(sequence), " [已识别参考序列] ", task, count=1, flags=re.IGNORECASE)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()


def _find_motif_starts(sequence: str | None, motif: str) -> list[int]:
    seq = _normalize_amino_acid_sequence(sequence)
    normalized_motif = _normalize_amino_acid_sequence(motif)
    if not seq or not normalized_motif:
        return []
    starts: list[int] = []
    width = len(normalized_motif)
    for index in range(0, len(seq) - width + 1):
        if seq[index : index + width] == normalized_motif:
            starts.append(index + 1)
    return starts


def _find_fixed_residue_motif_start(fixed_residues: list[dict[str, Any]], motif: str) -> int | None:
    normalized_motif = _normalize_amino_acid_sequence(motif)
    if not normalized_motif:
        return None
    position_map = {
        int(item.get("position") or 0): str(item.get("residue") or "").strip().upper()
        for item in fixed_residues
        if isinstance(item, dict)
    }
    starts: list[int] = []
    width = len(normalized_motif)
    for position in sorted(position_map):
        if all(position_map.get(position + offset) == normalized_motif[offset] for offset in range(width)):
            starts.append(position)
    if not starts:
        return None
    return starts[0]


def resolve_gfp_constraint_profile(
    req: DesignRequest,
    settings: Any,
    *,
    resolved_sequence: str | None = None,
    requested_fixed_residues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    use_gfp_constraints = "gfp" in req.task.lower()
    motif = str(settings.gfp_chromophore_motif or "SYG").strip().upper() or "SYG"
    chromophore_start = int(settings.gfp_chromophore_start)
    chromophore_source = "settings_default"
    requested_items = requested_fixed_residues or []

    fixed_start = _find_fixed_residue_motif_start(requested_items, motif)
    if fixed_start is not None:
        chromophore_start = fixed_start
        chromophore_source = "fixed_residues"
    else:
        sequence_starts = _find_motif_starts(resolved_sequence, motif)
        if len(sequence_starts) == 1:
            chromophore_start = sequence_starts[0]
            chromophore_source = "input_sequence"

    return {
        "use_gfp_constraints": use_gfp_constraints,
        "require_gfp_chromophore": settings.require_gfp_chromophore,
        "gfp_reference_length": len(resolved_sequence) if resolved_sequence else int(settings.gfp_reference_length),
        "gfp_chromophore_start": chromophore_start,
        "gfp_chromophore_motif": motif,
        "gfp_chromophore_source": chromophore_source,
    }


def resolve_input_sequence(req: DesignRequest) -> tuple[str | None, str | None, str]:
    explicit = _normalize_amino_acid_sequence(req.sequence)
    if explicit:
        return explicit, "field", req.task

    inline = _extract_inline_sequence(req.task)
    if inline:
        return inline, "task_inline", _strip_inline_sequence(req.task, inline)

    return None, None, req.task


def build_multimodal_context(
    req: DesignRequest,
    *,
    resolved_sequence: str | None = None,
    sequence_source: str | None = None,
    gfp_constraint_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    annotations = [item.model_dump() for item in (req.function_annotations or [])]
    fixed_residues = [
        {"position": item.position, "residue": item.residue.strip().upper()}
        for item in (req.fixed_residues or [])
    ]
    return {
        "input_sequence": resolved_sequence,
        "input_sequence_source": sequence_source,
        "input_pdb_path": req.pdb_path,
        "input_pdb_text": bool(req.pdb_text and req.pdb_text.strip()),
        "input_function_annotations": annotations,
        "input_function_keywords": req.function_keywords or [],
        "input_fixed_residues": fixed_residues,
        "input_sequence_length": req.sequence_length,
        "detected_inline_sequence": sequence_source == "task_inline",
        "gfp_constraint_profile": dict(gfp_constraint_profile or {}),
        "evolution_request": {
            "population_size": req.population_size,
            "elite_size": req.elite_size,
            "parent_pool_size": req.parent_pool_size,
            "mutations_per_parent": req.mutations_per_parent,
        },
    }


def multimodal_task_text(
    req: DesignRequest,
    *,
    task_text: str | None = None,
    resolved_sequence: str | None = None,
) -> str:
    base_task = task_text if task_text is not None else req.task
    extras: list[str] = []
    if resolved_sequence:
        extras.append(f"已提供参考序列：{resolved_sequence}")
    if req.pdb_path:
        extras.append(f"已提供结构文件路径：{req.pdb_path}")
    elif req.pdb_text:
        extras.append("已提供 PDB 结构文本")
    if req.function_keywords:
        extras.append("功能关键词：" + ", ".join(req.function_keywords))
    if req.function_annotations:
        labels = [item.label for item in req.function_annotations]
        extras.append("功能注释：" + ", ".join(labels))
    if req.sequence_length:
        extras.append(f"目标长度：{req.sequence_length}")
    if not extras:
        return base_task
    return base_task + "\n\n多模态上下文：\n- " + "\n- ".join(extras)

def resolve_sequence_constraints(
    req: DesignRequest,
    settings: Any,
    *,
    resolved_sequence: str | None = None,
    gfp_constraint_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested = [
        {"position": item.position, "residue": item.residue.strip().upper()}
        for item in (req.fixed_residues or [])
    ]
    profile = dict(gfp_constraint_profile or {})
    use_gfp_constraints = bool(profile.get("use_gfp_constraints")) if profile else "gfp" in req.task.lower()
    if use_gfp_constraints:
        motif_start = int(profile.get("gfp_chromophore_start") or settings.gfp_chromophore_start)
        motif = str(profile.get("gfp_chromophore_motif") or settings.gfp_chromophore_motif or "SYG").strip().upper()
        requested.extend(
            {"position": motif_start + index, "residue": residue}
            for index, residue in enumerate(motif)
        )

    fixed_residues = merge_fixed_residues(requested) if requested else []
    reference_length = None
    if resolved_sequence:
        reference_length = len(resolved_sequence)
    elif req.sequence_length:
        reference_length = int(req.sequence_length)
    elif use_gfp_constraints:
        reference_length = int(settings.gfp_reference_length)

    return {
        "reference_length": reference_length,
        "fixed_residues": fixed_residues,
        "gfp_reference_length": int(profile.get("gfp_reference_length") or reference_length or 0),
        "gfp_chromophore_start": int(profile.get("gfp_chromophore_start") or settings.gfp_chromophore_start),
        "gfp_chromophore_motif": str(profile.get("gfp_chromophore_motif") or settings.gfp_chromophore_motif or "SYG"),
        "gfp_chromophore_source": str(profile.get("gfp_chromophore_source") or "settings_default"),
        "require_gfp_chromophore": bool(
            profile.get("require_gfp_chromophore", settings.require_gfp_chromophore)
        ),
    }


def build_initial_sequences(
    req: DesignRequest,
    executor: ToolExecutor,
    candidates_per_round: int,
    *,
    resolved_sequence: str | None = None,
) -> list[str]:
    items: list[str] = []
    if resolved_sequence:
        items.append(resolved_sequence)

    if req.pdb_path or (req.pdb_text and req.pdb_text.strip()):
        items.extend(
            executor.inverse_fold(
                pdb_path=req.pdb_path,
                pdb_text=req.pdb_text,
                num_candidates=max(1, min(candidates_per_round, 4)),
                temperature=0.8,
                num_steps=1,
            )
        )

    if req.function_keywords or req.function_annotations:
        annotations = [item.model_dump() for item in (req.function_annotations or [])]
        generated = executor.generate_with_function(
            sequence=resolved_sequence,
            sequence_length=req.sequence_length,
            function_annotations=annotations,
            function_keywords=req.function_keywords,
            num_candidates=max(1, min(candidates_per_round, 4)),
            temperature=0.8,
            num_steps=8,
        )
        items.extend(generated.get("sequences", []))

    deduped: list[str] = []
    seen: set[str] = set()
    for sequence in items:
        value = (sequence or "").strip().upper()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped[: max(candidates_per_round * 2, 4)]


class FunctionGenerateRequest(BaseModel):
    sequence: str | None = None
    sequence_length: int | None = Field(default=None, ge=1, le=4096)
    function_annotations: list[FunctionAnnotationInput] | None = None
    function_keywords: list[str] | None = None
    num_candidates: int = Field(default=4, ge=1, le=64)
    temperature: float = Field(default=0.8, gt=0)
    num_steps: int = Field(default=1, ge=1, le=4096)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return load_chat_ui()


@app.get("/chat", response_class=HTMLResponse)
def chat_page() -> str:
    return load_chat_ui()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ui/status")
def ui_status() -> dict[str, Any]:
    settings = get_settings()
    data: dict[str, Any] = {
        "agent": {"status": "ok", "app_name": settings.app_name},
        "llm": {
            "configured": bool(settings.openai_api_key),
            "model": settings.llm_model,
            "base_url_configured": bool(settings.openai_base_url),
        },
        "esm3": {
            "configured_backend": settings.esm3_backend,
            "server_url": settings.esm3_server_url,
            "status": "unknown",
        },
    }
    if settings.esm3_backend != "http" or not settings.esm3_server_url:
        return data

    try:
        resp = requests.get(
            settings.esm3_server_url.rstrip("/") + "/health",
            timeout=min(max(settings.request_timeout, 1), 10),
        )
        resp.raise_for_status()
        payload = resp.json()
        data["esm3"] = {
            "configured_backend": settings.esm3_backend,
            "server_url": settings.esm3_server_url,
            "status": "ok",
            "health": payload,
        }
    except Exception as exc:  # noqa: BLE001
        data["esm3"]["status"] = "error"
        data["esm3"]["error"] = str(exc)
    return data


def build_scoring_summary(
    settings: Any,
    best_metadata: dict[str, Any],
    *,
    sequence_constraints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    constraints = sequence_constraints or {}
    return {
        "backend": settings.scoring_backend,
        "score_version": best_metadata.get("score_version"),
        "require_gfp_chromophore": constraints.get("require_gfp_chromophore", settings.require_gfp_chromophore),
        "gfp_reference_length": constraints.get("gfp_reference_length", settings.gfp_reference_length),
        "gfp_chromophore_start": constraints.get("gfp_chromophore_start", settings.gfp_chromophore_start),
        "gfp_chromophore_motif": constraints.get("gfp_chromophore_motif", settings.gfp_chromophore_motif),
        "gfp_chromophore_source": constraints.get("gfp_chromophore_source"),
        "surrogate_model_path": settings.surrogate_model_path,
        "surrogate_model_type": settings.surrogate_model_type,
        "surrogate_use_structure_features": settings.surrogate_use_structure_features,
        "surrogate_ensemble_size": settings.surrogate_ensemble_size,
        "surrogate_feature_backend": settings.surrogate_feature_backend,
        "use_rosetta": settings.use_rosetta,
        "rosetta_topn": settings.rosetta_topn,
    }


@app.post("/chat_reasoning")
def chat_reasoning(req: ChatReasoningRequest) -> dict[str, Any]:
    settings = get_settings()
    reasoner = ResultReasoner(settings)
    try:
        reply = reasoner.reply(
            message=req.message,
            latest_result=req.latest_result,
            conversation=[item.model_dump() for item in req.conversation],
            current_mode=req.current_mode,
            previous_best_sequence=req.previous_best_sequence,
        )
        return {"reply": reply}
    except Exception as exc:
        LOGGER.exception("Chat reasoning failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/design_protein")
def design_protein(req: DesignRequest) -> dict[str, Any]:
    settings = get_settings()
    planner = LLMPlanner(settings)
    executor = ToolExecutor(settings)

    try:
        run_created_at = datetime.now(timezone.utc).isoformat()
        resolved_sequence, sequence_source, normalized_task = resolve_input_sequence(req)
        requested_fixed_residues = [
            {"position": item.position, "residue": item.residue.strip().upper()}
            for item in (req.fixed_residues or [])
        ]
        gfp_constraint_profile = resolve_gfp_constraint_profile(
            req,
            settings,
            resolved_sequence=resolved_sequence,
            requested_fixed_residues=requested_fixed_residues,
        )
        enriched_task = multimodal_task_text(
            req,
            task_text=normalized_task,
            resolved_sequence=resolved_sequence,
        )
        plan = planner.plan(enriched_task)
        plan["input_modalities"] = {
            "sequence": bool(req.sequence),
            "structure": bool(req.pdb_path or (req.pdb_text and req.pdb_text.strip())),
            "function": bool(req.function_keywords or req.function_annotations),
        }
        max_iterations = req.max_iterations or plan.get("max_iterations", settings.max_iterations)
        candidates_per_round = req.candidates_per_round or plan.get("candidates_per_round", settings.default_candidates)
        patience = req.patience or plan.get("patience", settings.default_patience)
        plan["max_iterations"] = max_iterations
        plan["candidates_per_round"] = candidates_per_round
        plan["patience"] = patience
        plan["evolution"] = {
            "population_size": req.population_size or max(candidates_per_round * 2, 8),
            "elite_size": req.elite_size or 2,
            "parent_pool_size": req.parent_pool_size or max(2, min(max(candidates_per_round, 4), candidates_per_round * 2)),
            "mutations_per_parent": req.mutations_per_parent or 3,
        }
        multimodal_context = build_multimodal_context(
            req,
            resolved_sequence=resolved_sequence,
            sequence_source=sequence_source,
            gfp_constraint_profile=gfp_constraint_profile,
        )
        multimodal_context["sequence_constraints"] = resolve_sequence_constraints(
            req,
            settings,
            resolved_sequence=resolved_sequence,
            gfp_constraint_profile=gfp_constraint_profile,
        )
        initial_sequences = build_initial_sequences(
            req,
            executor,
            candidates_per_round,
            resolved_sequence=resolved_sequence,
        )
        seed_prompt = resolved_sequence
        memory = ExperimentMemory(
            run_metadata={
                "schema_version": 1,
                "task": req.task,
                "created_at": run_created_at,
                "seed_sequence": seed_prompt,
                "reference_length": multimodal_context["sequence_constraints"].get("reference_length"),
                "chromophore_start": multimodal_context["sequence_constraints"].get("gfp_chromophore_start"),
                "chromophore_motif": multimodal_context["sequence_constraints"].get("gfp_chromophore_motif"),
                "sequence_constraints": multimodal_context["sequence_constraints"],
            }
        )

        if "gfp" in req.task.lower():
            workflow = GFPOptimizer(executor, memory=memory)
            result = workflow.run(
                task=enriched_task,
                max_iterations=max_iterations,
                candidates_per_round=candidates_per_round,
                patience=patience,
                seed_prompt=seed_prompt,
                initial_sequences=initial_sequences,
                multimodal_context=multimodal_context,
                evolution_config=plan.get("evolution", {}),
            )
        else:
            loop_engine = ExperimentLoopEngine(executor, memory)
            result = loop_engine.run(
                plan=plan,
                task=enriched_task,
                seed_prompt=seed_prompt,
                initial_sequences=initial_sequences,
                multimodal_context=multimodal_context,
            )

        best_record = result.get("best") if isinstance(result, dict) else None
        best_metadata = best_record.get("metadata", {}) if isinstance(best_record, dict) else {}
        scoring_summary = build_scoring_summary(
            settings,
            best_metadata,
            sequence_constraints=multimodal_context.get("sequence_constraints"),
        )
        ensure_active_learning_layout()
        run_artifact_path = timestamped_run_path(req.task, created_at=run_created_at)
        active_model_version = (
            best_metadata.get("model_version")
            or (Path(settings.surrogate_model_path).name if settings.surrogate_model_path else None)
        )
        memory.update_run_metadata(
            plan=plan,
            input_context=multimodal_context,
            generation_stats=result.get("generation_stats", []),
            evolution_config=result.get("evolution_config", plan.get("evolution", {})),
            scoring=scoring_summary,
            surrogate_model_version=active_model_version,
            run_artifact_path=str(run_artifact_path),
        )
        memory.save_json(run_artifact_path)

        return {
            "task": req.task,
            "input_context": multimodal_context,
            "plan": plan,
            "history": result["records"],
            "best_sequences": result["best"],
            "best_candidate": result["best"],
            "generation_stats": result.get("generation_stats", []),
            "evolution_config": result.get("evolution_config", plan.get("evolution", {})),
            "scoring": scoring_summary,
            "run_artifact_path": str(run_artifact_path),
        }
    except Exception as exc:
        LOGGER.exception("Protein design execution failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/inverse_fold")
def inverse_fold(req: InverseFoldRequest) -> dict[str, Any]:
    settings = get_settings()
    executor = ToolExecutor(settings)
    try:
        sequences = executor.inverse_fold(
            pdb_path=req.pdb_path,
            pdb_text=req.pdb_text,
            num_candidates=req.num_candidates,
            temperature=req.temperature,
            num_steps=req.num_steps,
        )
        return {
            "sequences": sequences,
            "num_candidates": len(sequences),
        }
    except Exception as exc:
        LOGGER.exception("Inverse folding execution failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/generate_with_function")
def generate_with_function(req: FunctionGenerateRequest) -> dict[str, Any]:
    settings = get_settings()
    executor = ToolExecutor(settings)
    try:
        annotations = [item.model_dump() for item in (req.function_annotations or [])]
        return executor.generate_with_function(
            sequence=req.sequence,
            sequence_length=req.sequence_length,
            function_annotations=annotations,
            function_keywords=req.function_keywords,
            num_candidates=req.num_candidates,
            temperature=req.temperature,
            num_steps=req.num_steps,
        )
    except Exception as exc:
        LOGGER.exception("Function-conditioned generation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
