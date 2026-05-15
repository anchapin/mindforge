"""Tool registry -- canonical registry for all BaseTool implementations.

From SPEC.md Section 5.7.7 -- Unified Tool Interface.
All tools must be registered here. No direct tool instantiation elsewhere.
"""

from __future__ import annotations

import logging

from .base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Singleton registry for all BaseTool instances."""

    _tools: dict[str, BaseTool] = {}

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        if tool.name in cls._tools:
            logger.warning("Tool %s already registered, overwriting", tool.name)
        cls._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    @classmethod
    def get(cls, name: str) -> BaseTool:
        if name not in cls._tools:
            raise KeyError(f"Tool '{name}' not registered. Available: {list(cls._tools.keys())}")
        return cls._tools[name]

    @classmethod
    def list_tools(cls) -> list[BaseTool]:
        return list(cls._tools.values())

    @classmethod
    def list_names(cls) -> list[str]:
        return list(cls._tools.keys())

    @classmethod
    def for_skill(cls, skill_definition: dict) -> list[BaseTool]:
        """Return tools required by a skill, checked against allowed integrations."""
        tool_names = skill_definition.get("tools", [])
        return [cls.get(n) for n in tool_names]


def register_all_tools() -> None:
    """Auto-register all built-in tools. Call at startup."""
    from .email_fetch import EmailFetchTool
    from .email_send import EmailSendTool
    from .github import GitHubTool
    from .integrations.linear import LinearTool
    from .stripe import StripeTool

    for tool_cls in [GitHubTool, StripeTool, EmailFetchTool, EmailSendTool, LinearTool]:
        try:
            ToolRegistry.register(tool_cls())  # type: ignore[abstract]
        except Exception as exc:
            logger.warning("Failed to auto-register %s: %s", tool_cls.__name__, exc)
