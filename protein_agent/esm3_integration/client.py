"""Unified client for HTTP, local deployment, and generated-Python ESM3 backends."""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import requests

try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None

from protein_agent.config.settings import Settings

LOGGER = logging.getLogger(__name__)


class ESM3Client:
    """Backend-aware ESM3 client used by the agent tool layer."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.server_url = (settings.esm3_server_url or "").rstrip("/")
        self.http = requests.Session()
        self.http.headers.update({"User-Agent": "esm3-agent/real-esm3"})
        self.codegen_client = None
        if settings.openai_api_key and settings.allow_generated_python:
            if OpenAI is None:
                LOGGER.warning(
                    "openai package is not installed; generated Python fallback is disabled"
                )
            else:
                self.codegen_client = OpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                )

    def generate(self, prompt: str, num_candidates: int = 4, temperature: float = 0.8) -> dict[str, Any]:
        return self._call(
            "generate",
            {
                "prompt": prompt,
                "sequence": prompt,
                "num_candidates": num_candidates,
                "temperature": temperature,
                "model": self.settings.esm3_model_name,
            },
        )

    def mutate(self, sequence: str, num_mutations: int = 3, num_candidates: int = 4) -> dict[str, Any]:
        return self._call(
            "mutate",
            {
                "sequence": sequence,
                "num_mutations": num_mutations,
                "num_candidates": num_candidates,
                "model": self.settings.esm3_model_name,
            },
        )

    def predict_structure(self, sequence: str) -> dict[str, Any]:
        return self._call(
            "predict_structure",
            {
                "sequence": sequence,
                "model": self.settings.esm3_model_name,
            },
        )

    def inverse_fold(
        self,
        pdb_path: str | None = None,
        pdb_text: str | None = None,
        num_candidates: int = 4,
        temperature: float = 0.8,
        num_steps: int = 1,
    ) -> dict[str, Any]:
        return self._call(
            "inverse_fold",
            {
                "pdb_path": pdb_path or "",
                "pdb_text": pdb_text or "",
                "num_candidates": num_candidates,
                "temperature": temperature,
                "num_steps": num_steps,
                "model": self.settings.esm3_model_name,
            },
        )

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
        return self._call(
            "generate_with_function",
            {
                "sequence": sequence or "",
                "sequence_length": sequence_length or 0,
                "function_annotations": function_annotations or [],
                "function_keywords": function_keywords or [],
                "num_candidates": num_candidates,
                "temperature": temperature,
                "num_steps": num_steps,
                "model": self.settings.esm3_model_name,
            },
        )

    def _call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        backends = self._backend_order()
        errors: list[str] = []
        for backend in backends:
            try:
                if backend == "http":
                    return self._call_http(operation, payload)
                if backend == "local":
                    return self._call_local_bridge(operation, payload)
                if backend == "generated":
                    return self._call_generated_python(operation, payload, errors)
            except Exception as exc:  # noqa: BLE001
                detail = f"{backend}: {exc}"
                errors.append(detail)
                LOGGER.warning("ESM3 backend '%s' failed: %s", backend, exc)

        if len(backends) == 1 and len(errors) == 1:
            _, _, detail = errors[0].partition(": ")
            raise RuntimeError(detail or errors[0])

        joined = " | ".join(errors) if errors else "no backend available"
        raise RuntimeError(f"ESM3 {operation} failed across backends: {joined}")

    def _backend_order(self) -> list[str]:
        backend = (self.settings.esm3_backend or "auto").strip().lower()
        if backend == "http":
            return ["http"]
        if backend == "local":
            order = ["local"]
            if self.settings.allow_generated_python:
                order.append("generated")
            return order
        if backend == "generated":
            return ["generated"]

        order: list[str] = []
        if self.server_url:
            order.append("http")
        if self._has_local_config():
            order.append("local")
        if self.settings.allow_generated_python:
            order.append("generated")
        if not order:
            order = ["http", "local"]
            if self.settings.allow_generated_python:
                order.append("generated")
        return order

    def _has_local_config(self) -> bool:
        return any(
            [
                self.settings.esm3_root,
                self.settings.esm3_project_dir,
                self.settings.esm3_weights_dir,
                self.settings.esm3_data_dir,
                self.settings.esm3_generate_entrypoint,
                self.settings.esm3_mutate_entrypoint,
                self.settings.esm3_structure_entrypoint,
                self.settings.esm3_inverse_fold_entrypoint,
                self.settings.esm3_function_generate_entrypoint,
                self.settings.esm3_extra_pythonpath,
            ]
        )

    def _call_http(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.server_url:
            raise RuntimeError("PROTEIN_AGENT_ESM3_SERVER_URL is not configured")
        path_map = {
            "generate": "/generate_sequence",
            "mutate": "/mutate_sequence",
            "predict_structure": "/predict_structure",
            "inverse_fold": "/inverse_fold",
            "generate_with_function": "/generate_with_function",
        }
        path = path_map.get(operation)
        if not path:
            raise RuntimeError(f"unsupported HTTP operation: {operation}")

        headers: dict[str, str] = {}
        if self.settings.esm3_server_api_key:
            headers["Authorization"] = f"Bearer {self.settings.esm3_server_api_key}"
        if self.settings.esm3_server_headers_json:
            extra = json.loads(self.settings.esm3_server_headers_json)
            if not isinstance(extra, dict):
                raise RuntimeError("PROTEIN_AGENT_ESM3_SERVER_HEADERS_JSON must decode to an object")
            headers.update({str(k): str(v) for k, v in extra.items()})

        url = f"{self.server_url}{path}"
        try:
            resp = self.http.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.settings.request_timeout,
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(self._format_http_error(resp)) from exc
        except requests.RequestException as exc:
            raise RuntimeError(f"HTTP request to {url} failed: {exc}") from exc

        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data

    def _format_http_error(self, response: requests.Response) -> str:
        detail = self._extract_http_error_detail(response)
        status = f"HTTP {response.status_code}"
        location = response.url or self.server_url or "ESM3 server"
        if detail:
            return f"{status} from {location}: {detail}"
        reason = (response.reason or "request failed").strip()
        return f"{status} from {location}: {reason}"

    def _extract_http_error_detail(self, response: requests.Response) -> str | None:
        text = (response.text or "").strip()
        if not text:
            return None

        try:
            data = response.json()
        except ValueError:
            return text[:400]

        if isinstance(data, dict):
            for key in ("detail", "error", "message"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if value:
                    return json.dumps(value, ensure_ascii=False)[:400]
            return json.dumps(data, ensure_ascii=False)[:400]

        return json.dumps(data, ensure_ascii=False)[:400]

    def _call_local_bridge(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        python_path = (self.settings.esm3_python_path or "").strip()
        if not python_path:
            raise RuntimeError("PROTEIN_AGENT_ESM3_PYTHON_PATH is not configured")

        bridge_path = Path(__file__).with_name("bridge.py")
        proc = subprocess.run(
            [python_path, str(bridge_path)],
            input=json.dumps({"operation": operation, **payload}),
            text=True,
            capture_output=True,
            timeout=self.settings.request_timeout,
            env=self._build_local_env(),
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip())

        data = self._parse_json_blob(proc.stdout)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data

    def _call_generated_python(
        self,
        operation: str,
        payload: dict[str, Any],
        previous_errors: list[str],
    ) -> dict[str, Any]:
        if not self.codegen_client:
            raise RuntimeError(
                "generated Python fallback is disabled, missing OpenAI credentials, or openai package is not installed"
            )

        prompt = {
            "goal": "Write Python code that talks to a locally deployed ESM3 stack and returns one JSON object.",
            "operation": operation,
            "payload": payload,
            "previous_errors": previous_errors[-4:],
            "runtime_contract": {
                "input": "Read one JSON object from stdin.",
                "output": {
                    "generate": {"sequences": ["AASEQ"]},
                    "mutate": {"sequences": ["AASEQ"]},
                    "predict_structure": {"structure": {}, "confidence": 0.0},
                    "inverse_fold": {"sequences": ["AASEQ"]},
                    "generate_with_function": {"sequences": ["AASEQ"], "function_annotations": []},
                },
                "rules": [
                    "Output Python code only.",
                    "Do not use markdown fences.",
                    "Do not use network.",
                    "Use deployment paths from environment variables.",
                    "Print exactly one JSON object to stdout.",
                ],
                "env_vars": [
                    "PROTEIN_AGENT_ESM3_ROOT",
                    "PROTEIN_AGENT_ESM3_PROJECT_DIR",
                    "PROTEIN_AGENT_ESM3_WEIGHTS_DIR",
                    "PROTEIN_AGENT_ESM3_DATA_DIR",
                    "PROTEIN_AGENT_ESM3_MODEL_NAME",
                    "PROTEIN_AGENT_ESM3_DEVICE",
                ],
            },
        }
        response = self.codegen_client.responses.create(
            model=self.settings.generated_python_model or self.settings.llm_model,
            input=[
                {
                    "role": "system",
                    "content": "You write concise Python utilities for a local protein-engineering runtime.",
                },
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
        )
        code = self._strip_code_fences(response.output_text)
        if not code.strip():
            raise RuntimeError("generated Python fallback returned empty code")

        tmp_dir = Path(tempfile.mkdtemp(prefix="esm3_codegen_"))
        script_path = tmp_dir / "generated_esm3_operation.py"
        script_path.write_text(code, encoding="utf-8")

        proc = subprocess.run(
            [self.settings.esm3_python_path, str(script_path)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=self.settings.generated_python_timeout,
            env=self._build_local_env(),
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip())
        data = self._parse_json_blob(proc.stdout)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(str(data["error"]))
        return data

    def _build_local_env(self) -> dict[str, str]:
        env = os.environ.copy()
        mappings = {
            "PROTEIN_AGENT_ESM3_ROOT": self.settings.esm3_root or "",
            "PROTEIN_AGENT_ESM3_PROJECT_DIR": self.settings.esm3_project_dir or "",
            "PROTEIN_AGENT_ESM3_WEIGHTS_DIR": self.settings.esm3_weights_dir or "",
            "PROTEIN_AGENT_ESM3_DATA_DIR": self.settings.esm3_data_dir or "",
            "PROTEIN_AGENT_ESM3_MODEL_NAME": self.settings.esm3_model_name or "",
            "PROTEIN_AGENT_ESM3_DEVICE": self.settings.esm3_device or "",
            "PROTEIN_AGENT_ESM3_GENERATE_ENTRYPOINT": self.settings.esm3_generate_entrypoint or "",
            "PROTEIN_AGENT_ESM3_MUTATE_ENTRYPOINT": self.settings.esm3_mutate_entrypoint or "",
            "PROTEIN_AGENT_ESM3_STRUCTURE_ENTRYPOINT": self.settings.esm3_structure_entrypoint or "",
            "PROTEIN_AGENT_ESM3_INVERSE_FOLD_ENTRYPOINT": self.settings.esm3_inverse_fold_entrypoint or "",
            "PROTEIN_AGENT_ESM3_FUNCTION_GENERATE_ENTRYPOINT": self.settings.esm3_function_generate_entrypoint or "",
            "PROTEIN_AGENT_ESM3_EXTRA_PYTHONPATH": self.settings.esm3_extra_pythonpath or "",
        }
        env.update(mappings)
        return env

    def _parse_json_blob(self, blob: str) -> dict[str, Any]:
        text = (blob or "").strip()
        if not text:
            raise RuntimeError("empty output from ESM3 bridge")
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line.startswith("{") or not line.endswith("}"):
                continue
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue

        matches = re.findall(r"\{.*\}", text, flags=re.DOTALL)
        for candidate in reversed(matches):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                continue
        raise RuntimeError(f"unable to parse JSON output: {text[:400]}")

    def _strip_code_fences(self, code: str) -> str:
        text = code.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:python)?", "", text, count=1).strip()
            if text.endswith("```"):
                text = text[:-3].strip()
        return text
