from __future__ import annotations

import importlib
import sys
import types
import unittest
from unittest.mock import patch

from protein_agent.config.settings import Settings


def _install_test_stubs() -> None:
    executor_module = types.ModuleType("protein_agent.agent.executor")
    executor_module.ToolExecutor = type("ToolExecutor", (), {})
    sys.modules.setdefault("protein_agent.agent.executor", executor_module)

    planner_module = types.ModuleType("protein_agent.agent.planner")
    planner_module.LLMPlanner = type("LLMPlanner", (), {})
    sys.modules.setdefault("protein_agent.agent.planner", planner_module)

    reasoner_module = types.ModuleType("protein_agent.agent.reasoner")
    reasoner_module.ResultReasoner = type("ResultReasoner", (), {})
    sys.modules.setdefault("protein_agent.agent.reasoner", reasoner_module)

    workflow_module = types.ModuleType("protein_agent.agent.workflow")
    workflow_module.ExperimentLoopEngine = type("ExperimentLoopEngine", (), {})
    sys.modules.setdefault("protein_agent.agent.workflow", workflow_module)

    memory_module = types.ModuleType("protein_agent.memory.experiment_memory")
    memory_module.ExperimentMemory = type("ExperimentMemory", (), {})
    sys.modules.setdefault("protein_agent.memory.experiment_memory", memory_module)

    gfp_module = types.ModuleType("protein_agent.workflows.gfp_optimizer")
    gfp_module.GFPOptimizer = type("GFPOptimizer", (), {})
    sys.modules.setdefault("protein_agent.workflows.gfp_optimizer", gfp_module)


_install_test_stubs()
api_main = importlib.import_module("protein_agent.api.main")
DesignRequest = api_main.DesignRequest
design_protein = api_main.design_protein


class DummyPlanner:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def plan(self, task: str) -> dict[str, object]:
        return {
            "workflow": "iterative_protein_optimization",
            "target": "GFP",
            "max_iterations": 8,
            "patience": 2,
            "candidates_per_round": 24,
            "steps": ["generate_candidates"],
        }


class DummyExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings


class DummyGFPOptimizer:
    def __init__(self, executor: DummyExecutor) -> None:
        self.executor = executor

    def run(
        self,
        task: str,
        max_iterations: int,
        candidates_per_round: int,
        patience: int,
        seed_prompt: str | None = None,
        initial_sequences: list[str] | None = None,
        multimodal_context: dict | None = None,
        evolution_config: dict | None = None,
    ) -> dict:
        best = {
            "sequence": seed_prompt or "SEQ",
            "score": 1.23,
            "iteration": 1,
            "metadata": {
                "score_mode": "hybrid",
                "score_version": "xgb_ensemble_v1_randomsplit:hybrid_v1",
                "surrogate_available": True,
                "model_version": "xgb_ensemble_v1_randomsplit",
            },
        }
        return {
            "records": [best],
            "best": best,
            "generation_stats": [
                {
                    "iteration": 1,
                    "population_size": (evolution_config or {}).get("population_size"),
                    "elite_size": (evolution_config or {}).get("elite_size"),
                    "parent_pool_size": (evolution_config or {}).get("parent_pool_size"),
                    "mutations_per_parent": (evolution_config or {}).get("mutations_per_parent"),
                }
            ],
            "evolution_config": evolution_config or {},
        }


class DesignAPITests(unittest.TestCase):
    def test_gfp_request_overrides_are_reflected_in_response_plan_and_scoring(self) -> None:
        settings = Settings(
            scoring_backend="hybrid",
            surrogate_model_path="/models/gfp_surrogate/xgb_ensemble_v1_randomsplit",
            surrogate_model_type="xgboost",
            surrogate_ensemble_size=5,
            surrogate_feature_backend="hybrid",
            surrogate_use_structure_features=False,
            require_gfp_chromophore=True,
            gfp_reference_length=236,
            gfp_chromophore_start=63,
            gfp_chromophore_motif="SYG",
        )
        req = DesignRequest(
            task="Design an improved GFP and iteratively optimize it",
            sequence="KGEELFTGVV",
            max_iterations=1,
            candidates_per_round=2,
            patience=1,
        )

        with (
            patch("protein_agent.api.main.get_settings", return_value=settings),
            patch("protein_agent.api.main.LLMPlanner", DummyPlanner),
            patch("protein_agent.api.main.ToolExecutor", DummyExecutor),
            patch("protein_agent.api.main.build_initial_sequences", return_value=[]),
            patch("protein_agent.api.main.GFPOptimizer", DummyGFPOptimizer),
        ):
            result = design_protein(req)

        self.assertEqual(result["plan"]["max_iterations"], 1)
        self.assertEqual(result["plan"]["candidates_per_round"], 2)
        self.assertEqual(result["plan"]["patience"], 1)
        self.assertEqual(result["plan"]["evolution"]["population_size"], 8)
        self.assertEqual(result["plan"]["evolution"]["elite_size"], 2)
        self.assertEqual(result["plan"]["evolution"]["parent_pool_size"], 4)
        self.assertEqual(result["plan"]["evolution"]["mutations_per_parent"], 3)
        self.assertEqual(result["scoring"]["backend"], "hybrid")
        self.assertEqual(result["scoring"]["surrogate_model_path"], "/models/gfp_surrogate/xgb_ensemble_v1_randomsplit")
        self.assertEqual(result["scoring"]["gfp_reference_length"], 236)
        self.assertEqual(result["scoring"]["gfp_chromophore_start"], 63)
        self.assertEqual(result["best_candidate"]["metadata"]["score_mode"], "hybrid")
        self.assertTrue(result["best_candidate"]["metadata"]["surrogate_available"])
        self.assertEqual(result["best_candidate"]["metadata"]["model_version"], "xgb_ensemble_v1_randomsplit")


if __name__ == "__main__":
    unittest.main()
