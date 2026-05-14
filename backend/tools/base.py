"""Base tool interface. From SPEC.md Section 5.7.7."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResult:
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tool_name: str = ""
    latency_ms: float = 0.0


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    input_schema: dict = {}
    retry_config: dict = {"max_attempts": 3, "backoff_factor": 2, "jitter": True}
    required_integrations: list[str] = []

    @abstractmethod
    async def execute(self, action: str, **kwargs) -> ToolResult: ...

    @abstractmethod
    async def validate_auth(self) -> bool:
        """Check credentials are present and not expired."""
        ...
