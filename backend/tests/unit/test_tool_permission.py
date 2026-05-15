"""Unit tests for tool permission enforcement (Issue #99)."""

from __future__ import annotations

import pytest

from backend.tools.base import BaseTool, ToolResult


class DummyTool(BaseTool):
    """Minimal concrete BaseTool for testing permission checks."""

    name = "dummy_api"
    description = "Test tool for permission enforcement"
    required_integrations = ["test"]

    async def _execute(self, action: str, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={}, tool_name=self.name)

    async def validate_auth(self, token: str | None = None) -> bool:
        return True


class RestrictedTool(BaseTool):
    """Tool that restricts to specific agents."""

    name = "restricted_api"
    description = "Restricted test tool"
    required_integrations = ["test"]
    allowed_agents = ["engineer", "coo"]

    async def _execute(self, action: str, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={}, tool_name=self.name)

    async def validate_auth(self, token: str | None = None) -> bool:
        return True


class WriteActionTool(BaseTool):
    """Tool with write-permission-gated actions."""

    name = "write_tool"
    description = "Tool with write-permission actions"
    required_integrations = ["test"]
    allowed_agents = ["cmo"]

    async def _execute(self, action: str, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={}, tool_name=self.name)

    async def validate_auth(self, token: str | None = None) -> bool:
        return True


class ResearcherTool(BaseTool):
    """Researcher agent tool — restricted to read-only actions."""

    name = "researcher_api"
    description = "Researcher-only read tool"
    required_integrations = ["test"]
    allowed_agents = ["researcher"]

    async def _execute(self, action: str, **kwargs) -> ToolResult:
        return ToolResult(success=True, data={}, tool_name=self.name)

    async def validate_auth(self, token: str | None = None) -> bool:
        return True


# -------------------------------------------------------------------------------------------------
# Test: allowed_agents block-all default
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unrestricted_tool_allows_any_agent():
    """When allowed_agents is empty (default), no agent is blocked."""
    tool = DummyTool()
    result = await tool.execute("read", agent_identity="engineer")
    assert result.success is True


@pytest.mark.asyncio
async def test_unrestricted_tool_blocks_named_agents_if_set():
    """When allowed_agents is set, only named agents pass."""
    tool = RestrictedTool()
    # Engineer is in allowed_agents — should succeed
    result = await tool.execute("read", agent_identity="engineer", integration_config={"allowed_agents": ["engineer", "coo"]})
    assert result.success is True


# -------------------------------------------------------------------------------------------------
# Test: agent_identity=None skips permission check (backwards compatibility)
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_none_agent_identity_skips_check():
    """When agent_identity is None, permission check is skipped (legacy callers)."""
    tool = RestrictedTool()
    # No agent_identity — should bypass check
    result = await tool.execute("read", agent_identity=None)
    assert result.success is True


# -------------------------------------------------------------------------------------------------
# Test: error response when agent not authorized
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_not_authorized_returns_error():
    """When agent is not in allowed_agents, ToolResult returns success=False."""
    tool = RestrictedTool()
    # Researcher is NOT in allowed_agents — should fail
    result = await tool.execute("read", agent_identity="researcher", integration_config={"allowed_agents": ["engineer", "coo"]})
    assert result.success is False
    assert "not authorized" in result.error


# -------------------------------------------------------------------------------------------------
# Test: error response with custom integration_config
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_custom_allowed_agents_restricts_access():
    """Custom integration_config with allowed_agents restricts access."""
    tool = DummyTool()
    result = await tool.execute("read", agent_identity="unknown", integration_config={"allowed_agents": ["engineer"]})
    assert result.success is False
    assert "not authorized" in result.error
