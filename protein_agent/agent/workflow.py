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

    def run(
        self,
        plan: dict[str, Any],
        task: str,
        seed_prompt: str | None = None,
        initial_sequences: list[str] | None = None,
        multimodal_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        max_iterations = min(int(plan.get("max_iterations", 20)), 100)
        patience = int(plan.get("patience", 8))
        candidates_per_round = int(plan.get("candidates_per_round", 8))
        evolution = plan.get("evolution") or {}
        population_size = max(candidates_per_round, int(evolution.get("population_size", max(candidates_per_round * 2, 8))))
        elite_size = max(1, min(int(evolution.get("elite_size", 2)), population_size))
        parent_pool_size = max(elite_size, min(int(evolution.get("parent_pool_size", max(2, elite_size * 2))), population_size))
        mutations_per_parent = max(1, int(evolution.get("mutations_per_parent", 3)))

        no_improve_rounds = 0
        best_score = float("-inf")
        context = multimodal_context or {}
        generation_stats: list[dict[str, Any]] = []

        population = self._initialize_population(
            initial_sequences=initial_sequences,
            seed_prompt=seed_prompt or task,
            population_size=population_size,
        )

        for iteration in range(1, max_iterations + 1):
            LOGGER.info("Iteration %s started", iteration)
            evaluated = []
            for candidate in population:
                seq = candidate["sequence"]
                result = self.executor.evaluate(seq)
                record = ExperimentRecord(
                    sequence=seq,
                    mutation_history=list(candidate.get("mutation_history") or []),
                    score=result["score"],
                    iteration=iteration,
                    structure_data=result["structure"],
                    metadata={**result.get("metrics", {}), **context},
                )
                self.memory.add(record)
                evaluated.append(record)

            ranked = sorted(evaluated, key=lambda r: r.score, reverse=True)
            top = ranked[:elite_size]
            generation_stats.append(
                self._generation_summary(
                    iteration=iteration,
                    ranked=ranked,
                    population_size=len(population),
                    elite_size=elite_size,
                    parent_pool_size=parent_pool_size,
                    mutations_per_parent=mutations_per_parent,
                )
            )
            current_best = top[0].score
            if current_best > best_score:
                best_score = current_best
                no_improve_rounds = 0
            else:
                no_improve_rounds += 1

            if no_improve_rounds >= patience:
                LOGGER.info("Stopping due to no improvement for %s rounds", patience)
                break

            population = self._next_generation(
                ranked=ranked,
                population_size=population_size,
                elite_size=elite_size,
                parent_pool_size=parent_pool_size,
                mutations_per_parent=mutations_per_parent,
                seed_prompt=seed_prompt or task,
            )

        return {
            **self.memory.to_dict(),
            "generation_stats": generation_stats,
            "evolution_config": {
                "population_size": population_size,
                "elite_size": elite_size,
                "parent_pool_size": parent_pool_size,
                "mutations_per_parent": mutations_per_parent,
            },
        }

    def _initialize_population(
        self,
        initial_sequences: list[str] | None,
        seed_prompt: str,
        population_size: int,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        for sequence in initial_sequences or []:
            value = (sequence or "").strip().upper()
            if not value or value in seen:
                continue
            seen.add(value)
            items.append({"sequence": value, "mutation_history": []})

        if len(items) < population_size:
            generated = self.executor.generate(seed_prompt, population_size - len(items))
            for sequence in generated:
                value = (sequence or "").strip().upper()
                if not value or value in seen:
                    continue
                seen.add(value)
                items.append({"sequence": value, "mutation_history": ["initial_generate"]})
                if len(items) >= population_size:
                    break

        return items[:population_size]

    def _generation_summary(
        self,
        iteration: int,
        ranked: list[ExperimentRecord],
        population_size: int,
        elite_size: int,
        parent_pool_size: int,
        mutations_per_parent: int,
    ) -> dict[str, Any]:
        scores = [record.score for record in ranked]
        average_score = sum(scores) / len(scores) if scores else 0.0
        best = ranked[0] if ranked else None
        worst = ranked[-1] if ranked else None
        return {
            "iteration": iteration,
            "population_size": population_size,
            "elite_size": elite_size,
            "parent_pool_size": parent_pool_size,
            "mutations_per_parent": mutations_per_parent,
            "best_score": best.score if best else 0.0,
            "average_score": average_score,
            "worst_score": worst.score if worst else 0.0,
            "best_sequence": best.sequence if best else None,
        }

    def _next_generation(
        self,
        ranked: list[ExperimentRecord],
        population_size: int,
        elite_size: int,
        parent_pool_size: int,
        mutations_per_parent: int,
        seed_prompt: str,
    ) -> list[dict[str, Any]]:
        if not ranked:
            return self._initialize_population(initial_sequences=None, seed_prompt=seed_prompt, population_size=population_size)

        next_population: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_candidate(sequence: str, mutation_history: list[str]) -> None:
            value = (sequence or "").strip().upper()
            if not value or value in seen or len(next_population) >= population_size:
                return
            seen.add(value)
            next_population.append({"sequence": value, "mutation_history": mutation_history})

        elites = ranked[:elite_size]
        parents = ranked[:parent_pool_size]
        for elite in elites:
            add_candidate(elite.sequence, list(elite.mutation_history) + ["elite_keep"])

        if not parents:
            parents = elites

        while len(next_population) < population_size:
            progressed = False
            for parent in parents:
                offspring_count = max(1, min(3, population_size - len(next_population)))
                mutated = self.executor.mutate(
                    parent.sequence,
                    num_mutations=mutations_per_parent,
                    num_candidates=offspring_count,
                )
                for sequence in mutated:
                    add_candidate(sequence, list(parent.mutation_history) + [f"mutate_from_iter_{parent.iteration}"])
                    progressed = True
                    if len(next_population) >= population_size:
                        break
                if len(next_population) >= population_size:
                    break
            if len(next_population) >= population_size:
                break
            if not progressed:
                generated = self.executor.generate(seed_prompt, population_size - len(next_population))
                for sequence in generated:
                    add_candidate(sequence, ["regenerate_population"])
                if not generated:
                    break

        return next_population[:population_size]
