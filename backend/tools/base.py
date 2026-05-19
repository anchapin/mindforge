"""Base tool interface. From SPEC.md Section 5.7.7."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


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
    allowed_agents: list[str] | None = None

    async def execute(
        self,
        action: str,
        agent_identity: str | None = None,
        integration_config: dict | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute a tool action with optional permission enforcement.

        Args:
            action: The action to perform (e.g., 'send', 'refund', 'commits')
            agent_identity: The name of the agent calling this tool (e.g., 'cmo', 'engineer')
            integration_config: Integration config from DB (with allowed_agents, permissions)
            **kwargs: Action-specific parameters

        Returns:
            ToolResult with success status, data, or error
        """
        import time

        start = time.monotonic()

        if agent_identity:
            allowed_agents = None
            if integration_config:
                allowed_agents = integration_config.get("allowed_agents")
            if allowed_agents is None:
                allowed_agents = getattr(self, "allowed_agents", None)
            if allowed_agents:
                if isinstance(allowed_agents, str):
                    allowed_agents = json.loads(allowed_agents)
                if agent_identity not in allowed_agents:
                    logger.warning(
                        "Tool %s unauthorized for agent %s (allowed: %s)",
                        self.name,
                        agent_identity,
                        allowed_agents,
                    )
                    return ToolResult(
                        success=False,
                        error=f"Agent '{agent_identity}' not authorized for {self.name}",
                        tool_name=self.name,
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

            permissions = None
            if integration_config:
                permissions = integration_config.get("permissions")
            if permissions:
                if isinstance(permissions, str):
                    permissions = json.loads(permissions)
                required_action = f"{self.name}:{action}"
                allowed_actions = permissions.get("allowed_actions", [])
                if required_action not in allowed_actions:
                    logger.warning(
                        "Tool %s action %s not permitted for agent %s",
                        self.name,
                        action,
                        agent_identity,
                    )
                    return ToolResult(
                        success=False,
                        error=f"Permission '{required_action}' not granted for {self.name}",
                        tool_name=self.name,
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

        return await self._execute(action, **kwargs)

    @abstractmethod
    async def _execute(self, action: str, **kwargs) -> ToolResult:
        """Internal execute implementation. Override in subclasses."""
        ...

    @abstractmethod
    async def validate_auth(self, token: str | None = None) -> bool:
        """Check the supplied credential is accepted by the integration.

        Implementations should perform a cheap, read-only API call (typically
        a token-introspection endpoint or a `/me` route) and return:
          - True  -> 2xx response (token is valid)
          - False -> 4xx (auth failed) OR network error

        Subclasses that take additional credentials (e.g. IMAP host, SMTP
        port) may accept extra keyword arguments.
        """
        ...
