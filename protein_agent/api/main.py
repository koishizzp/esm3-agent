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


class DesignRequest(BaseModel):
    task: str = Field(..., description="Natural language protein engineering request")
    max_iterations: int | None = Field(default=None, ge=1, le=100)
    candidates_per_round: int | None = Field(default=None, ge=1, le=64)
    patience: int | None = Field(default=None, ge=1, le=100)


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
        plan = planner.plan(req.task)
        if "gfp" in req.task.lower():
            workflow = GFPOptimizer(executor)
            result = workflow.run(
                task=req.task,
                max_iterations=req.max_iterations or plan.get("max_iterations", settings.max_iterations),
                candidates_per_round=req.candidates_per_round
                or plan.get("candidates_per_round", settings.default_candidates),
                patience=req.patience or plan.get("patience", settings.default_patience),
            )
        else:
            memory = ExperimentMemory()
            loop_engine = ExperimentLoopEngine(executor, memory)
            plan["max_iterations"] = req.max_iterations or plan.get("max_iterations", settings.max_iterations)
            plan["candidates_per_round"] = req.candidates_per_round or plan.get(
                "candidates_per_round", settings.default_candidates
            )
            plan["patience"] = req.patience or plan.get("patience", settings.default_patience)
            result = loop_engine.run(plan=plan, task=req.task)

        return {
            "task": req.task,
            "plan": plan,
            "history": result["records"],
            "best_sequences": result["best"],
        }
    except Exception as exc:
        LOGGER.exception("Protein design execution failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
