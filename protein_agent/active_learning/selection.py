"""Selection helpers for diverse active-learning batches."""
from __future__ import annotations

from typing import Iterable

import numpy as np


def hamming_distance(seq_a: str, seq_b: str) -> int:
    if len(seq_a) != len(seq_b):
        return abs(len(seq_a) - len(seq_b)) + sum(a != b for a, b in zip(seq_a, seq_b))
    return sum(a != b for a, b in zip(seq_a, seq_b))


def select_diverse_topk(
    sequences: Iterable[str],
    acquisition_scores: np.ndarray | list[float],
    *,
    k: int,
    min_hamming: int = 0,
) -> list[tuple[str, float]]:
    sequence_list = [str(sequence).strip().upper() for sequence in sequences]
    score_array = np.asarray(acquisition_scores, dtype=np.float32)
    ranked = sorted(
        zip(sequence_list, score_array.tolist()),
        key=lambda item: item[1],
        reverse=True,
    )

    if min_hamming <= 0:
        return ranked[: max(0, k)]

    selected: list[tuple[str, float]] = []
    for sequence, score in ranked:
        if all(hamming_distance(sequence, chosen) >= min_hamming for chosen, _ in selected):
            selected.append((sequence, float(score)))
        if len(selected) >= k:
            break
    return selected
