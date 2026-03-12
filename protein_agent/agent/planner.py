"""LLM planner that converts NL requests into structured JSON plans."""
from __future__ import annotations

import json
import logging
from typing import Any

try:
    from openai import OpenAI
except Exception:  # noqa: BLE001
    OpenAI = None

from protein_agent.config.settings import Settings

LOGGER = logging.getLogger(__name__)


class LLMPlanner:
    """Plan generator backed by an OpenAI-compatible client."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None
        if settings.openai_api_key:
            if OpenAI is None:
                LOGGER.warning("openai package unavailable; using deterministic fallback planner.")
            else:
                self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    def plan(self, task: str) -> dict[str, Any]:
        if not self.client:
            LOGGER.warning("OpenAI client unavailable; using deterministic fallback planner.")
            return self._fallback_plan(task)

        prompt = {
            "task": task,
            "required_steps": [
                "generate_candidates",
                "evaluate_candidates",
                "select_best_variants",
                "mutate_best_variants",
                "repeat_until_stop",
            ],
            "output_format": {
                "workflow": "string",
                "target": "string",
                "max_iterations": "int",
                "patience": "int",
                "candidates_per_round": "int",
                "steps": ["string"],
            },
        }

        try:
            response = self.client.responses.create(
                model=self.settings.llm_model,
                input=[
                    {
                        "role": "system",
                        "content": "You are a protein engineering planner. Output valid JSON only.",
                    },
                    {"role": "user", "content": json.dumps(prompt)},
                ],
            )
            text = response.output_text.strip()
        except Exception:  # noqa: BLE001
            LOGGER.exception("LLM planner request failed; using deterministic fallback planner.")
            return self._fallback_plan(task)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            LOGGER.exception("LLM planner returned non-JSON output; falling back.")
            return self._fallback_plan(task)

    def _fallback_plan(self, task: str) -> dict[str, Any]:
        target = "GFP" if "gfp" in task.lower() else "target_protein"
        return {
            "workflow": "iterative_protein_optimization",
            "target": target,
            "max_iterations": self.settings.max_iterations,
            "patience": self.settings.default_patience,
            "candidates_per_round": self.settings.default_candidates,
            "steps": [
                "generate_candidates",
                "evaluate_candidates",
                "select_best_variants",
                "mutate_best_variants",
                "repeat_until_stop",
            ],
        }
