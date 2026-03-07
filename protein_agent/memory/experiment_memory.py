"""Experiment memory store for iterative protein engineering."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ExperimentRecord:
    sequence: str
    mutation_history: list[str]
    score: float
    iteration: int
    structure_data: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ExperimentMemory:
    """In-memory registry of all experiment records and best variants."""

    def __init__(self) -> None:
        self._records: list[ExperimentRecord] = []

    def add(self, record: ExperimentRecord) -> None:
        self._records.append(record)

    def all_records(self) -> list[ExperimentRecord]:
        return list(self._records)

    def top_k(self, k: int = 5) -> list[ExperimentRecord]:
        return sorted(self._records, key=lambda r: r.score, reverse=True)[:k]

    def best(self) -> ExperimentRecord | None:
        if not self._records:
            return None
        return max(self._records, key=lambda r: r.score)

    def to_dict(self) -> dict[str, Any]:
        return {
            "records": [
                {
                    "sequence": r.sequence,
                    "mutation_history": r.mutation_history,
                    "score": r.score,
                    "iteration": r.iteration,
                    "structure_data": r.structure_data,
                    "metadata": r.metadata,
                }
                for r in self._records
            ],
            "best": None
            if self.best() is None
            else {
                "sequence": self.best().sequence,
                "score": self.best().score,
                "mutation_history": self.best().mutation_history,
                "iteration": self.best().iteration,
            },
        }
