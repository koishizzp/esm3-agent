"""REST API for autonomous protein design."""
from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
import requests

from protein_agent.agent.executor import ToolExecutor
from protein_agent.agent.planner import LLMPlanner
from protein_agent.agent.workflow import ExperimentLoopEngine
from protein_agent.config.settings import get_settings
from protein_agent.memory.experiment_memory import ExperimentMemory
from protein_agent.workflows.gfp_optimizer import GFPOptimizer

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)
app = FastAPI(title="Autonomous Protein Design Agent", version="1.0.0")


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


def build_multimodal_context(req: DesignRequest) -> dict[str, Any]:
    annotations = [item.model_dump() for item in (req.function_annotations or [])]
    return {
        "input_sequence": req.sequence,
        "input_pdb_path": req.pdb_path,
        "input_pdb_text": bool(req.pdb_text and req.pdb_text.strip()),
        "input_function_annotations": annotations,
        "input_function_keywords": req.function_keywords or [],
        "input_sequence_length": req.sequence_length,
        "evolution_request": {
            "population_size": req.population_size,
            "elite_size": req.elite_size,
            "parent_pool_size": req.parent_pool_size,
            "mutations_per_parent": req.mutations_per_parent,
        },
    }


def multimodal_task_text(req: DesignRequest) -> str:
    extras: list[str] = []
    if req.sequence:
        extras.append(f"已提供参考序列：{req.sequence}")
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
        return req.task
    return req.task + "\n\n多模态上下文：\n- " + "\n- ".join(extras)


def build_initial_sequences(
    req: DesignRequest,
    executor: ToolExecutor,
    candidates_per_round: int,
) -> list[str]:
    items: list[str] = []
    if req.sequence and req.sequence.strip():
        items.append(req.sequence.strip().upper())

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
            sequence=req.sequence,
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


@app.post("/design_protein")
def design_protein(req: DesignRequest) -> dict[str, Any]:
    settings = get_settings()
    planner = LLMPlanner(settings)
    executor = ToolExecutor(settings)

    try:
        enriched_task = multimodal_task_text(req)
        plan = planner.plan(enriched_task)
        plan["input_modalities"] = {
            "sequence": bool(req.sequence),
            "structure": bool(req.pdb_path or (req.pdb_text and req.pdb_text.strip())),
            "function": bool(req.function_keywords or req.function_annotations),
        }
        candidates_per_round = req.candidates_per_round or plan.get("candidates_per_round", settings.default_candidates)
        plan["evolution"] = {
            "population_size": req.population_size or max(candidates_per_round * 2, 8),
            "elite_size": req.elite_size or 2,
            "parent_pool_size": req.parent_pool_size or max(2, min(max(candidates_per_round, 4), candidates_per_round * 2)),
            "mutations_per_parent": req.mutations_per_parent or 3,
        }
        multimodal_context = build_multimodal_context(req)
        initial_sequences = build_initial_sequences(req, executor, candidates_per_round)
        seed_prompt = req.sequence.strip().upper() if req.sequence and req.sequence.strip() else None

        if "gfp" in req.task.lower():
            workflow = GFPOptimizer(executor)
            result = workflow.run(
                task=enriched_task,
                max_iterations=req.max_iterations or plan.get("max_iterations", settings.max_iterations),
                candidates_per_round=candidates_per_round,
                patience=req.patience or plan.get("patience", settings.default_patience),
                seed_prompt=seed_prompt,
                initial_sequences=initial_sequences,
                multimodal_context=multimodal_context,
                evolution_config=plan.get("evolution", {}),
            )
        else:
            memory = ExperimentMemory()
            loop_engine = ExperimentLoopEngine(executor, memory)
            plan["max_iterations"] = req.max_iterations or plan.get("max_iterations", settings.max_iterations)
            plan["candidates_per_round"] = candidates_per_round
            plan["patience"] = req.patience or plan.get("patience", settings.default_patience)
            result = loop_engine.run(
                plan=plan,
                task=enriched_task,
                seed_prompt=seed_prompt,
                initial_sequences=initial_sequences,
                multimodal_context=multimodal_context,
            )

        return {
            "task": req.task,
            "input_context": multimodal_context,
            "plan": plan,
            "history": result["records"],
            "best_sequences": result["best"],
            "generation_stats": result.get("generation_stats", []),
            "evolution_config": result.get("evolution_config", plan.get("evolution", {})),
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
