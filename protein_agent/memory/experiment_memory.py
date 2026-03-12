"""Experiment memory store for iterative protein engineering."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from protein_agent.memory.storage import read_json, write_json


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

    def __init__(self, run_metadata: dict[str, Any] | None = None) -> None:
        self._records: list[ExperimentRecord] = []
        self._run_metadata: dict[str, Any] = dict(run_metadata or {})

    def add(self, record: ExperimentRecord) -> None:
        self._records.append(record)

    @property
    def run_metadata(self) -> dict[str, Any]:
        return dict(self._run_metadata)

    def update_run_metadata(self, **updates: Any) -> None:
        for key, value in updates.items():
            if value is not None:
                self._run_metadata[key] = value

    def all_records(self) -> list[ExperimentRecord]:
        return list(self._records)

    def _valid_records(self) -> list[ExperimentRecord]:
        return [
            record
            for record in self._records
            if (record.metadata or {}).get("valid_candidate", True) is not False
        ]

    def _eligible_records(self) -> list[ExperimentRecord]:
        valid_records = self._valid_records()
        return valid_records or list(self._records)

    def top_k(self, k: int = 5) -> list[ExperimentRecord]:
        return sorted(self._eligible_records(), key=lambda r: r.score, reverse=True)[:k]

    def best(self) -> ExperimentRecord | None:
        valid_records = self._valid_records()
        if not valid_records:
            return None
        return max(valid_records, key=lambda r: r.score)

    def _serialize_record(self, record: ExperimentRecord) -> dict[str, Any]:
        return {
            "sequence": record.sequence,
            "mutation_history": record.mutation_history,
            "score": record.score,
            "iteration": record.iteration,
            "structure_data": record.structure_data,
            "metadata": record.metadata,
        }

    def _deserialize_record(self, payload: dict[str, Any]) -> ExperimentRecord:
        return ExperimentRecord(
            sequence=str(payload.get("sequence") or ""),
            mutation_history=list(payload.get("mutation_history") or []),
            score=float(payload.get("score") or 0.0),
            iteration=int(payload.get("iteration") or 0),
            structure_data=payload.get("structure_data"),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        best_record = self.best()
        return {
            **self._run_metadata,
            "records": [self._serialize_record(record) for record in self._records],
            "best": None if best_record is None else self._serialize_record(best_record),
        }

    def save_json(self, path: str | Path) -> Path:
        return write_json(self.to_dict(), path)

    @classmethod
    def load_json(cls, path: str | Path) -> "ExperimentMemory":
        payload = read_json(path)
        if not isinstance(payload, dict):
            raise ValueError(f"Experiment memory JSON must be an object: {path}")

        run_metadata = {
            key: value
            for key, value in payload.items()
            if key not in {"records", "best"}
        }
        memory = cls(run_metadata=run_metadata)
        for item in payload.get("records", []):
            if isinstance(item, dict):
                memory.add(memory._deserialize_record(item))
        return memory
