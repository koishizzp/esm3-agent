"""REST API for autonomous protein design."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from protein_agent.agent.executor import ToolExecutor
from protein_agent.agent.planner import LLMPlanner
from protein_agent.agent.workflow import ExperimentLoopEngine
from protein_agent.config.settings import get_settings
from protein_agent.memory.experiment_memory import ExperimentMemory
from protein_agent.workflows.gfp_optimizer import GFPOptimizer

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)
app = FastAPI(title="Autonomous Protein Design Agent", version="1.0.0")


class DesignRequest(BaseModel):
    task: str = Field(..., description="Natural language protein engineering request")
    max_iterations: int | None = Field(default=None, ge=1, le=100)
    candidates_per_round: int | None = Field(default=None, ge=1, le=64)
    patience: int | None = Field(default=None, ge=1, le=100)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
