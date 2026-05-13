"""MindForge tools -- integration tool implementations.

Call register_all_tools() at startup to register built-in integrations.
"""

from .base import BaseTool, ToolResult
from .registry import ToolRegistry, register_all_tools

__all__ = ["ToolRegistry", "register_all_tools", "BaseTool", "ToolResult"]
