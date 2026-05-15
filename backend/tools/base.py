"""Base tool interface. From SPEC.md Section 5.7.7."""

from __future__ import annotations

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


class PermissionDeniedError(Exception):
    """Raised when an agent attempts an action it is not authorized for."""

    def __init__(self, agent_role: str, tool_name: str, action: str, reason: str = ""):
        self.agent_role = agent_role
        self.tool_name = tool_name
        self.action = action
        self.reason = reason
        super().__init__(
            f"Permission denied: agent '{agent_role}' cannot perform '{action}' "
            f"on tool '{tool_name}'{f' ({reason})' if reason else ''}"
        )


class BaseTool(ABC):
    name: str = ""
    description: str = ""
    input_schema: dict = {}
    retry_config: dict = {"max_attempts": 3, "backoff_factor": 2, "jitter": True}
    required_integrations: list[str] = []

    # Permission scoping — set per-tool or per-integration in DB
    # Allowed agent roles (e.g. ["engineer", "coo"]). Empty = block all.
    allowed_agents: list[str] = []
    # Action-specific permissions (e.g. {"refund": ["write"], "balance": ["read"]})
    # If an action is not listed, defaults to ["read"].
    permissions: dict[str, list[str]] = {}

    def get_permission_for_action(self, action: str) -> str:
        """Return the permission level required for an action.

        Returns 'write' for high-stakes actions, 'read' for everything else.
        Override to customize per-tool.
        """
        # High-stakes write actions (destructive/modifying)
        high_stakes = {
            "refund",
            "send",
            "send_email",
            "delete",
            "push",
            "create_pr",
            "merge_pr",
            "create_issue",
        }
        if action in high_stakes:
            return "write"
        return "read"

    def check_permissions(self, agent_role: str, action: str) -> None:
        """Validate that agent_role is allowed to perform action.

        Raises PermissionDeniedError if:
        - agent_role is None (no identity available — deny by default)
        - allowed_agents is non-empty and agent_role is not in it
        - the required permission for action is not granted

        Logs the denial with full context.
        """
        if agent_role is None:
            # No agent identity — deny by default to prevent bypass via
            # callers that don't propagate agent context.
            logger.warning(
                "Permission denied: no agent_role supplied for tool '%s' (action=%s)",
                self.name,
                action,
            )
            raise PermissionDeniedError(
                agent_role="<none>",
                tool_name=self.name,
                action=action,
                reason="no agent identity provided",
            )

        # Check allowed_agents — empty list means block all
        if self.allowed_agents and agent_role not in self.allowed_agents:
            logger.warning(
                "Permission denied: agent '%s' is not in allowed_agents for tool '%s' "
                "(allowed: %s, requested action: %s)",
                agent_role,
                self.name,
                self.allowed_agents,
                action,
            )
            raise PermissionDeniedError(
                agent_role=agent_role,
                tool_name=self.name,
                action=action,
                reason=f"agent '{agent_role}' is not permitted to use this tool",
            )

        # Check action-specific permission
        required_perm = self.get_permission_for_action(action)
        granted_perms = self.permissions.get(action, ["read"])

        # If the tool has no explicit permissions dict, assume ["read"] is enough
        if not self.permissions and required_perm == "read":
            return

        if required_perm not in granted_perms:
            logger.warning(
                "Permission denied: action '%s' on tool '%s' requires '%s' permission, "
                "but agent '%s' only has %s",
                action,
                self.name,
                required_perm,
                agent_role,
                granted_perms,
            )
            raise PermissionDeniedError(
                agent_role=agent_role,
                tool_name=self.name,
                action=action,
                reason=f"action '{action}' requires '{required_perm}' permission",
            )

    @abstractmethod
    async def execute(self, action: str, agent_role: str | None = None, **kwargs) -> ToolResult: ...

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
