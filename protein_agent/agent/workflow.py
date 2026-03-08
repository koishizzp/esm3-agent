"""Experiment loop engine for autonomous optimization."""
from __future__ import annotations

import logging
from typing import Any

from protein_agent.agent.executor import ToolExecutor
from protein_agent.memory.experiment_memory import ExperimentMemory, ExperimentRecord

LOGGER = logging.getLogger(__name__)


class ExperimentLoopEngine:
    def __init__(self, executor: ToolExecutor, memory: ExperimentMemory) -> None:
        self.executor = executor
        self.memory = memory

    def run(self, plan: dict[str, Any], task: str, seed_prompt: str | None = None) -> dict[str, Any]:
        max_iterations = min(int(plan.get("max_iterations", 20)), 100)
        patience = int(plan.get("patience", 8))
        candidates_per_round = int(plan.get("candidates_per_round", 8))

        no_improve_rounds = 0
        best_score = float("-inf")
        seed_sequences = self.executor.generate(seed_prompt or task, candidates_per_round)

        for iteration in range(1, max_iterations + 1):
            LOGGER.info("Iteration %s started", iteration)
            evaluated = []
            for seq in seed_sequences:
                result = self.executor.evaluate(seq)
                record = ExperimentRecord(
                    sequence=seq,
                    mutation_history=[] if iteration == 1 else ["iterative_mutation"],
                    score=result["score"],
                    iteration=iteration,
                    structure_data=result["structure"],
                    metadata=result.get("metrics", {}),
                )
                self.memory.add(record)
                evaluated.append(record)

            top = sorted(evaluated, key=lambda r: r.score, reverse=True)[:2]
            current_best = top[0].score
            if current_best > best_score:
                best_score = current_best
                no_improve_rounds = 0
            else:
                no_improve_rounds += 1

            if no_improve_rounds >= patience:
                LOGGER.info("Stopping due to no improvement for %s rounds", patience)
                break

            next_round = []
            for rec in top:
                next_round.extend(
                    self.executor.mutate(
                        rec.sequence,
                        num_mutations=3,
                        num_candidates=max(2, candidates_per_round // 2),
                    )
                )
            seed_sequences = next_round[: candidates_per_round * 2]

        return self.memory.to_dict()
