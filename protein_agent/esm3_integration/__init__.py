"""Integration helpers for real ESM3 backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import ESM3Client

__all__ = ["ESM3Client"]


def __getattr__(name: str):
    if name == "ESM3Client":
        from .client import ESM3Client

        return ESM3Client
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
