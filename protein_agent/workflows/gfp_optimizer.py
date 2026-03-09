"""Built-in GFP optimization workflow."""
from __future__ import annotations

from protein_agent.agent.executor import ToolExecutor
from protein_agent.agent.workflow import ExperimentLoopEngine
from protein_agent.gfp import GFP_SCAFFOLD
from protein_agent.memory.experiment_memory import ExperimentMemory


class GFPOptimizer:
    def __init__(self, executor: ToolExecutor) -> None:
        self.executor = executor
        self.memory = ExperimentMemory()
        self.loop_engine = ExperimentLoopEngine(executor, self.memory)

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
        plan = {
            "workflow": "gfp_optimizer",
            "target": "GFP",
            "max_iterations": max_iterations,
            "patience": patience,
            "candidates_per_round": candidates_per_round,
            "evolution": evolution_config or {},
            "steps": [
                "identify_gfp_scaffold",
                "generate_mutations",
                "predict_structure",
                "score_candidates",
                "select_best_variants",
                "repeat",
            ],
        }
        return self.loop_engine.run(
            plan=plan,
            task=task,
            seed_prompt=seed_prompt or GFP_SCAFFOLD,
            initial_sequences=initial_sequences,
            multimodal_context=multimodal_context,
        )
