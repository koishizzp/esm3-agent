"""Experiment loop engine for autonomous optimization."""
from __future__ import annotations

import logging
from typing import Any

from protein_agent.agent.executor import ToolExecutor
from protein_agent.constraints import SequenceConstraints
from protein_agent.memory.experiment_memory import ExperimentMemory, ExperimentRecord

LOGGER = logging.getLogger(__name__)


class ExperimentLoopEngine:
    def __init__(self, executor: ToolExecutor, memory: ExperimentMemory) -> None:
        self.executor = executor
        self.memory = memory

    def _build_scoring_context(
        self,
        plan: dict[str, Any],
        task: str,
        multimodal_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        target = str(plan.get("target") or "").strip()
        workflow = str(plan.get("workflow") or "").strip()
        task_text = str(task or "").strip()
        use_gfp_constraints = "gfp" in " ".join([target, workflow, task_text]).lower()
        context = multimodal_context or {}
        sequence_constraints = context.get("sequence_constraints") or {}
        return {
            "task": task_text,
            "target": target,
            "workflow": workflow,
            "use_gfp_constraints": use_gfp_constraints,
            "fixed_residues": sequence_constraints.get("fixed_residues") or [],
            "reference_length": sequence_constraints.get("reference_length"),
            "gfp_reference_length": sequence_constraints.get("reference_length"),
        }

    def _resolve_sequence_constraints(
        self,
        multimodal_context: dict[str, Any] | None,
    ) -> SequenceConstraints | None:
        context = multimodal_context or {}
        return SequenceConstraints.from_dict(context.get("sequence_constraints"))

    def _normalize_sequence(
        self,
        sequence: str,
        sequence_constraints: SequenceConstraints | None,
    ) -> str | None:
        value = (sequence or "").strip().upper()
        if not value:
            return None
        if sequence_constraints is None:
            return value
        return sequence_constraints.apply(value)

    def _selection_pool(self, records: list[ExperimentRecord]) -> list[ExperimentRecord]:
        valid_records = [
            record
            for record in records
            if (record.metadata or {}).get("valid_candidate", True) is not False
        ]
        return valid_records or records

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
        sequence_constraints = self._resolve_sequence_constraints(multimodal_context)
        scoring_context = self._build_scoring_context(plan, task, multimodal_context)

        population = self._initialize_population(
            initial_sequences=initial_sequences,
            seed_prompt=seed_prompt or task,
            population_size=population_size,
            sequence_constraints=sequence_constraints,
        )

        for iteration in range(1, max_iterations + 1):
            LOGGER.info("Iteration %s started", iteration)
            evaluated = []
            for candidate in population:
                seq = candidate["sequence"]
                result = self.executor.evaluate(seq, scoring_context=scoring_context)
                record = ExperimentRecord(
                    sequence=seq,
                    mutation_history=list(candidate.get("mutation_history") or []),
                    score=result["score"],
                    iteration=iteration,
                    structure_data=result["structure"],
                    metadata={
                        **result.get("metrics", {}),
                        "score_breakdown": result.get("score_breakdown", {}),
                        "valid_candidate": result.get("valid_candidate", True),
                        **context,
                    },
                )
                self.memory.add(record)
                evaluated.append(record)

            selection_pool = self._selection_pool(evaluated)
            ranked = sorted(selection_pool, key=lambda r: r.score, reverse=True)
            top = ranked[:elite_size]
            generation_stats.append(
                self._generation_summary(
                    iteration=iteration,
                    ranked=ranked,
                    population_size=len(population),
                    elite_size=elite_size,
                    parent_pool_size=parent_pool_size,
                    mutations_per_parent=mutations_per_parent,
                    valid_candidates=len(selection_pool),
                    invalid_candidates=max(0, len(evaluated) - len(selection_pool)),
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
                sequence_constraints=sequence_constraints,
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
        sequence_constraints: SequenceConstraints | None = None,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()

        for sequence in initial_sequences or []:
            value = self._normalize_sequence(sequence, sequence_constraints)
            if not value or value in seen:
                continue
            seen.add(value)
            items.append({"sequence": value, "mutation_history": []})

        if len(items) < population_size and items:
            seed_sequences = [item["sequence"] for item in items]
            for parent_sequence in seed_sequences:
                needed = population_size - len(items)
                if needed <= 0:
                    break
                mutated = self.executor.mutate(
                    parent_sequence,
                    num_mutations=3,
                    num_candidates=max(1, min(3, needed)),
                )
                for sequence in mutated:
                    value = self._normalize_sequence(sequence, sequence_constraints)
                    if not value or value in seen:
                        continue
                    seen.add(value)
                    items.append({"sequence": value, "mutation_history": ["initial_seed_mutate"]})
                    if len(items) >= population_size:
                        break

        if len(items) < population_size:
            generated = self.executor.generate(seed_prompt, population_size - len(items))
            for sequence in generated:
                value = self._normalize_sequence(sequence, sequence_constraints)
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
        valid_candidates: int,
        invalid_candidates: int,
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
            "valid_candidates": valid_candidates,
            "invalid_candidates": invalid_candidates,
        }

    def _next_generation(
        self,
        ranked: list[ExperimentRecord],
        population_size: int,
        elite_size: int,
        parent_pool_size: int,
        mutations_per_parent: int,
        seed_prompt: str,
        sequence_constraints: SequenceConstraints | None = None,
    ) -> list[dict[str, Any]]:
        if not ranked:
            return self._initialize_population(
                initial_sequences=None,
                seed_prompt=seed_prompt,
                population_size=population_size,
                sequence_constraints=sequence_constraints,
            )

        next_population: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add_candidate(sequence: str, mutation_history: list[str]) -> bool:
            value = self._normalize_sequence(sequence, sequence_constraints)
            if not value or value in seen or len(next_population) >= population_size:
                return False
            seen.add(value)
            next_population.append({"sequence": value, "mutation_history": mutation_history})
            return True

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
                    progressed = (
                        add_candidate(
                            sequence,
                            list(parent.mutation_history) + [f"mutate_from_iter_{parent.iteration}"],
                        )
                        or progressed
                    )
                    if len(next_population) >= population_size:
                        break
                if len(next_population) >= population_size:
                    break
            if len(next_population) >= population_size:
                break
            if not progressed:
                generated = self.executor.generate(seed_prompt, population_size - len(next_population))
                for sequence in generated:
                    progressed = add_candidate(sequence, ["regenerate_population"]) or progressed
                if not generated:
                    break
                if not progressed:
                    break

        return next_population[:population_size]
