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

    def _eligible_records(self) -> list[ExperimentRecord]:
        valid_records = [
            record
            for record in self._records
            if (record.metadata or {}).get("valid_candidate", True) is not False
        ]
        return valid_records or list(self._records)

    def top_k(self, k: int = 5) -> list[ExperimentRecord]:
        return sorted(self._eligible_records(), key=lambda r: r.score, reverse=True)[:k]

    def best(self) -> ExperimentRecord | None:
        eligible = self._eligible_records()
        if not eligible:
            return None
        return max(eligible, key=lambda r: r.score)

    def _serialize_record(self, record: ExperimentRecord) -> dict[str, Any]:
        return {
            "sequence": record.sequence,
            "mutation_history": record.mutation_history,
            "score": record.score,
            "iteration": record.iteration,
            "structure_data": record.structure_data,
            "metadata": record.metadata,
        }

    def to_dict(self) -> dict[str, Any]:
        best_record = self.best()
        return {
            "records": [self._serialize_record(record) for record in self._records],
            "best": None if best_record is None else self._serialize_record(best_record),
        }
