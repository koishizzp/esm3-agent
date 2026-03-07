"""Tool interface definitions."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]

    @abstractmethod
    def execute(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Run tool with validated input."""
