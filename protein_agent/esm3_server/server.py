"""FastAPI server exposing local ESM3 generation/mutation/structure endpoints."""
from __future__ import annotations

import logging
import os
import random
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

LOGGER = logging.getLogger(__name__)
app = FastAPI(title="ESM3 Model Server", version="1.0.0")

AMINO_ACIDS = "ACDEFGHIKLMNPQRSTVWY"


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
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = self._load_model()

    def _load_model(self) -> Any:
        try:
            from esm.models.esm3 import ESM3
        except Exception as exc:  # runtime dependency error
            raise RuntimeError("Failed to import ESM3. Install esm package in this environment.") from exc

        model_name = os.getenv("ESM3_MODEL_NAME", "esm3-open")
        LOGGER.info("Loading ESM3 model '%s' on %s", model_name, self.device)
        model = ESM3.from_pretrained(model_name)
        model = model.to(self.device)
        model.eval()
        return model

    def generate(self, prompt: str, num_candidates: int, temperature: float) -> list[str]:
        try:
            outputs = self.model.generate(
                prompt,
                num_steps=1,
                temperature=temperature,
                num_samples=num_candidates,
            )
            if isinstance(outputs, list):
                return [o.sequence if hasattr(o, "sequence") else str(o) for o in outputs]
            if hasattr(outputs, "sequence"):
                return [outputs.sequence]
            return [str(outputs)]
        except Exception as exc:
            raise RuntimeError(f"ESM3 generation failed: {exc}") from exc

    def mutate(self, sequence: str, num_mutations: int, num_candidates: int) -> list[str]:
        base = list(sequence.strip().upper())
        variants = []
        for _ in range(num_candidates):
            mutated = base.copy()
            for _ in range(num_mutations):
                idx = random.randrange(len(mutated))
                mutated[idx] = random.choice(AMINO_ACIDS)
            mutated_prompt = "".join(mutated)
            generated = self.generate(mutated_prompt, 1, temperature=0.9)
            variants.append(generated[0])
        return variants

    def predict_structure(self, sequence: str) -> dict[str, Any]:
        try:
            prediction = self.model.generate(sequence, track="structure", num_steps=1)
            confidence = float(getattr(prediction, "confidence", 0.0))
            return {
                "structure": getattr(prediction, "structure", None),
                "confidence": confidence,
                "device": self.device,
            }
        except Exception as exc:
            raise RuntimeError(f"Structure prediction failed: {exc}") from exc


SERVICE: ESM3Service | None = None


@app.on_event("startup")
def startup() -> None:
    global SERVICE
    SERVICE = ESM3Service()


@app.post("/generate_sequence")
def generate_sequence(req: GenerateRequest) -> dict[str, Any]:
    if SERVICE is None:
        raise HTTPException(status_code=503, detail="Model service unavailable")
    try:
        return {"sequences": SERVICE.generate(req.prompt, req.num_candidates, req.temperature)}
    except RuntimeError as exc:
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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/predict_structure")
def predict_structure(req: StructureRequest) -> dict[str, Any]:
    if SERVICE is None:
        raise HTTPException(status_code=503, detail="Model service unavailable")
    try:
        return SERVICE.predict_structure(req.sequence)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
