"""Acquisition functions for active-learning candidate selection."""
from __future__ import annotations

import numpy as np


def ucb_score(mu: float, sigma: float, lambda_: float = 0.5) -> float:
    """Upper Confidence Bound score for a single candidate."""
    return float(mu) + float(lambda_) * float(sigma)


def batch_ucb(
    mus: np.ndarray | list[float],
    sigmas: np.ndarray | list[float],
    lambda_: float = 0.5,
) -> np.ndarray:
    mean_array = np.asarray(mus, dtype=np.float32)
    std_array = np.asarray(sigmas, dtype=np.float32)
    return mean_array + float(lambda_) * std_array
