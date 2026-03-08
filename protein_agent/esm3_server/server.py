"""FastAPI server exposing local ESM3 generation/mutation/structure endpoints."""
from __future__ import annotations

import logging
import os
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from protein_agent.esm3_integration.bridge import (
    build_values,
    configure_paths,
    generate_with_model,
    load_direct_model,
    mutate_with_model,
    structure_with_model,
)

LOGGER = logging.getLogger(__name__)
app = FastAPI(title="ESM3 Model Server", version="1.0.0")


class GenerateRequest(BaseModel):
    prompt: str
    num_candidates: int = Field(default=4, ge=1, le=64)
    temperature: float = Field(default=0.8, gt=0)


class MutateRequest(BaseModel):
    sequence: str
    num_mutations: int = Field(default=3, ge=1, le=20)
    num_candidates: int = Field(default=4, ge=1, le=64)


class StructureRequest(BaseModel):
    sequence: str


class ESM3Service:
    def __init__(self) -> None:
        configured = os.getenv("PROTEIN_AGENT_ESM3_DEVICE", "").strip()
        self.device = configured or ("cuda" if torch.cuda.is_available() else "cpu")
        self.model = self._load_model()

    def _load_model(self) -> Any:
        configure_paths()
        model_name = (
            os.getenv("PROTEIN_AGENT_ESM3_MODEL_NAME", "").strip()
            or os.getenv("ESM3_MODEL_NAME", "").strip()
            or "esm3-open"
        )
        LOGGER.info("Loading ESM3 model '%s' on %s", model_name, self.device)
        payload = {"model": model_name}
        return load_direct_model(payload)

    def generate(self, prompt: str, num_candidates: int, temperature: float) -> list[str]:
        try:
            payload = {
                "prompt": prompt,
                "sequence": prompt,
                "num_candidates": num_candidates,
                "temperature": temperature,
                "device": self.device,
            }
            return generate_with_model(self.model, payload)["sequences"]
        except Exception as exc:
            raise RuntimeError(f"ESM3 generation failed: {exc}") from exc

    def mutate(self, sequence: str, num_mutations: int, num_candidates: int) -> list[str]:
        try:
            payload = {
                "sequence": sequence,
                "num_mutations": num_mutations,
                "num_candidates": num_candidates,
                "device": self.device,
            }
            return mutate_with_model(self.model, payload)["sequences"]
        except Exception as exc:
            raise RuntimeError(f"ESM3 mutation failed: {exc}") from exc

    def predict_structure(self, sequence: str) -> dict[str, Any]:
        try:
            payload = {"sequence": sequence, "device": self.device}
            result = structure_with_model(self.model, payload)
            result["device"] = self.device
            return result
        except Exception as exc:
            raise RuntimeError(f"Structure prediction failed: {exc}") from exc


SERVICE: ESM3Service | None = None


@app.on_event("startup")
def startup() -> None:
    global SERVICE
    SERVICE = ESM3Service()


@app.get("/health")
def health() -> dict[str, Any]:
    values = build_values({})
    return {
        "status": "ok",
        "device": values.get("device") or (SERVICE.device if SERVICE else "unknown"),
        "model": values.get("model"),
        "root": os.getenv("PROTEIN_AGENT_ESM3_ROOT", "").strip(),
        "project_dir": os.getenv("PROTEIN_AGENT_ESM3_PROJECT_DIR", "").strip(),
    }


@app.post("/generate_sequence")
def generate_sequence(req: GenerateRequest) -> dict[str, Any]:
    if SERVICE is None:
        raise HTTPException(status_code=503, detail="Model service unavailable")
    try:
        return {"sequences": SERVICE.generate(req.prompt, req.num_candidates, req.temperature)}
    except RuntimeError as exc:
        LOGGER.exception("ESM3 generate_sequence failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/mutate_sequence")
def mutate_sequence(req: MutateRequest) -> dict[str, Any]:
    if SERVICE is None:
        raise HTTPException(status_code=503, detail="Model service unavailable")
    try:
        return {
            "sequences": SERVICE.mutate(req.sequence, req.num_mutations, req.num_candidates)
        }
    except RuntimeError as exc:
        LOGGER.exception("ESM3 mutate_sequence failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/predict_structure")
def predict_structure(req: StructureRequest) -> dict[str, Any]:
    if SERVICE is None:
        raise HTTPException(status_code=503, detail="Model service unavailable")
    try:
        return SERVICE.predict_structure(req.sequence)
    except RuntimeError as exc:
        LOGGER.exception("ESM3 predict_structure failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
