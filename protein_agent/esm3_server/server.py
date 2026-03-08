"""FastAPI server exposing local ESM3 generation/mutation/structure endpoints."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from protein_agent.esm3_integration.bridge import (
    build_values,
    configure_paths,
    function_conditioned_generate_with_model,
    generate_with_model,
    inverse_fold_with_model,
    load_direct_model,
    mutate_with_model,
    structure_with_model,
)

LOGGER = logging.getLogger(__name__)
app = FastAPI(title="ESM3 Model Server", version="1.0.0")


def ensure_runtime_data_layout() -> None:
    root = os.getenv("PROTEIN_AGENT_ESM3_ROOT", "").strip()
    data_dir = os.getenv("PROTEIN_AGENT_ESM3_DATA_DIR", "").strip()
    if not data_dir:
        if not root:
            return
        data_dir = os.path.join(root, "data")

    data_path = Path(data_dir)
    function_path = data_path / "function"
    if not function_path.is_dir():
        return

    for source in function_path.iterdir():
        if not source.is_file():
            continue

        target = data_path / source.name
        if target.exists():
            continue

        try:
            os.symlink(source, target)
            LOGGER.info("Created compatibility symlink: %s -> %s", target, source)
            continue
        except OSError:
            pass

        shutil.copy2(source, target)
        LOGGER.info("Copied compatibility file: %s -> %s", source, target)


def ensure_runtime_paths() -> None:
    root = os.getenv("PROTEIN_AGENT_ESM3_ROOT", "").strip()
    weights = os.getenv("PROTEIN_AGENT_ESM3_WEIGHTS_DIR", "").strip()
    data = os.getenv("PROTEIN_AGENT_ESM3_DATA_DIR", "").strip()

    if root and os.path.isdir(root):
        os.chdir(root)
        os.environ["ESM_SOURCE_PATH"] = root
    if weights:
        os.environ["ESM3_SNAPSHOT_DIR"] = weights
    if data:
        os.environ["LOCAL_DATA_PATH"] = data
    os.environ.setdefault("INFRA_PROVIDER", "local")
    ensure_runtime_data_layout()


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


class FunctionGenerateRequest(BaseModel):
    sequence: str | None = None
    sequence_length: int | None = Field(default=None, ge=1, le=4096)
    function_annotations: list[FunctionAnnotationInput] | None = None
    function_keywords: list[str] | None = None
    num_candidates: int = Field(default=4, ge=1, le=64)
    temperature: float = Field(default=0.8, gt=0)
    num_steps: int = Field(default=1, ge=1, le=4096)


class ESM3Service:
    def __init__(self) -> None:
        ensure_runtime_paths()
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

    def inverse_fold(
        self,
        pdb_path: str | None,
        pdb_text: str | None,
        num_candidates: int,
        temperature: float,
        num_steps: int,
    ) -> list[str]:
        try:
            payload = {
                "pdb_path": pdb_path or "",
                "pdb_text": pdb_text or "",
                "num_candidates": num_candidates,
                "temperature": temperature,
                "num_steps": num_steps,
                "device": self.device,
            }
            return inverse_fold_with_model(self.model, payload)["sequences"]
        except Exception as exc:
            raise RuntimeError(f"Inverse folding failed: {exc}") from exc

    def generate_with_function(
        self,
        sequence: str | None,
        sequence_length: int | None,
        function_annotations: list[dict[str, Any]] | None,
        function_keywords: list[str] | None,
        num_candidates: int,
        temperature: float,
        num_steps: int,
    ) -> dict[str, Any]:
        try:
            payload = {
                "sequence": sequence or "",
                "sequence_length": sequence_length or 0,
                "function_annotations": function_annotations or [],
                "function_keywords": function_keywords or [],
                "num_candidates": num_candidates,
                "temperature": temperature,
                "num_steps": num_steps,
                "device": self.device,
            }
            result = function_conditioned_generate_with_model(self.model, payload)
            result["device"] = self.device
            return result
        except Exception as exc:
            raise RuntimeError(f"Function-conditioned generation failed: {exc}") from exc


SERVICE: ESM3Service | None = None


@app.on_event("startup")
def startup() -> None:
    global SERVICE
    ensure_runtime_paths()
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
        "cwd": os.getcwd(),
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


@app.post("/inverse_fold")
def inverse_fold(req: InverseFoldRequest) -> dict[str, Any]:
    if SERVICE is None:
        raise HTTPException(status_code=503, detail="Model service unavailable")
    try:
        return {
            "sequences": SERVICE.inverse_fold(
                req.pdb_path,
                req.pdb_text,
                req.num_candidates,
                req.temperature,
                req.num_steps,
            )
        }
    except RuntimeError as exc:
        LOGGER.exception("ESM3 inverse_fold failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/generate_with_function")
def generate_with_function(req: FunctionGenerateRequest) -> dict[str, Any]:
    if SERVICE is None:
        raise HTTPException(status_code=503, detail="Model service unavailable")
    try:
        annotations = []
        for item in req.function_annotations or []:
            annotations.append(item.model_dump())
        return SERVICE.generate_with_function(
            req.sequence,
            req.sequence_length,
            annotations,
            req.function_keywords,
            req.num_candidates,
            req.temperature,
            req.num_steps,
        )
    except RuntimeError as exc:
        LOGGER.exception("ESM3 generate_with_function failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
