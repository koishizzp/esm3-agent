"""Helpers for hard sequence constraints during design."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


AA_ALPHABET = set("ACDEFGHIKLMNPQRSTVWY")


@dataclass(frozen=True, slots=True)
class FixedResidue:
    position: int
    residue: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "residue": self.residue,
        }


@dataclass(slots=True)
class SequenceConstraints:
    reference_length: int | None = None
    fixed_residues: tuple[FixedResidue, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "reference_length": self.reference_length,
            "fixed_residues": [item.to_dict() for item in self.fixed_residues],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SequenceConstraints | None":
        if not isinstance(payload, dict):
            return None
        reference_length = payload.get("reference_length")
        fixed_items = payload.get("fixed_residues") or []
        normalized: list[FixedResidue] = []
        for item in fixed_items:
            if not isinstance(item, dict):
                continue
            position = int(item.get("position") or 0)
            residue = str(item.get("residue") or "").strip().upper()
            if position < 1 or residue not in AA_ALPHABET or len(residue) != 1:
                continue
            normalized.append(FixedResidue(position=position, residue=residue))
        return cls(
            reference_length=int(reference_length) if reference_length else None,
            fixed_residues=tuple(normalized),
        )

    def max_position(self) -> int:
        return max((item.position for item in self.fixed_residues), default=0)

    def apply(self, sequence: str) -> str | None:
        value = (sequence or "").strip().upper()
        if not value:
            return None
        if self.reference_length and len(value) != self.reference_length:
            return None
        if len(value) < self.max_position():
            return None
        chars = list(value)
        for item in self.fixed_residues:
            chars[item.position - 1] = item.residue
        return "".join(chars)

    def violations(self, sequence: str) -> list[dict[str, Any]]:
        value = (sequence or "").strip().upper()
        issues: list[dict[str, Any]] = []
        if not value:
            return issues
        for item in self.fixed_residues:
            observed = value[item.position - 1] if item.position <= len(value) else None
            if observed != item.residue:
                issues.append(
                    {
                        "position": item.position,
                        "expected": item.residue,
                        "observed": observed,
                    }
                )
        return issues


def merge_fixed_residues(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, str] = {}
    for item in items:
        position = int(item.get("position") or 0)
        residue = str(item.get("residue") or "").strip().upper()
        if position < 1 or residue not in AA_ALPHABET or len(residue) != 1:
            raise ValueError(f"Invalid fixed residue constraint: {item}")
        existing = merged.get(position)
        if existing is not None and existing != residue:
            raise ValueError(
                f"Conflicting fixed residue constraint at position {position}: {existing} vs {residue}"
            )
        merged[position] = residue
    return [
        {"position": position, "residue": residue}
        for position, residue in sorted(merged.items())
    ]
