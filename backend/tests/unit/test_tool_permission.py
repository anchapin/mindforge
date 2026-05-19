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


@pytest.mark.asyncio
async def test_tool_class_level_allowed_agents_enforced():
    """Tool's class-level allowed_agents is enforced when no integration_config provided."""
    tool = RestrictedTool()  # allowed_agents = ["engineer", "coo"]
    # Researcher is NOT in the tool's class-level allowed_agents
    result = await tool.execute("read", agent_identity="researcher")
    assert result.success is False
    assert "not authorized" in result.error


@pytest.mark.asyncio
async def test_integration_config_overrides_tool_allowed_agents():
    """Integration config can further restrict (narrow) access beyond tool's class-level."""
    tool = RestrictedTool()  # class-level: ["engineer", "coo"]
    # But integration_config only allows "coo"
    result = await tool.execute("read", agent_identity="coo", integration_config={"allowed_agents": ["coo"]})
    assert result.success is True
    # Engineer is in class-level but NOT in integration_config
    result2 = await tool.execute("read", agent_identity="engineer", integration_config={"allowed_agents": ["coo"]})
    assert result2.success is False
    assert "not authorized" in result2.error


@pytest.mark.asyncio
async def test_action_specific_permissions_checked():
    """Action-specific permissions from integration_config are validated."""
    tool = WriteActionTool()  # allowed_agents = ["cmo"]
    # integration_config has permissions restricting specific actions
    result = await tool.execute(
        "send",
        agent_identity="cmo",
        integration_config={
            "allowed_agents": ["cmo"],
            "permissions": {"allowed_actions": ["write_tool:read"]},  # only read allowed
        },
    )
    assert result.success is False
    assert "Permission" in result.error
    assert "write_tool:send" in result.error


@pytest.mark.asyncio
async def test_permission_error_logged_with_agent_identity():
    """Permission denial is logged with agent identity and requested action."""
    import io
    import logging

    tool = RestrictedTool()  # allowed_agents = ["engineer", "coo"]
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.WARNING)
    logger = logging.getLogger("backend.tools.base")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)

    try:
        result = await tool.execute("read", agent_identity="researcher")
        assert result.success is False

        log_output = log_stream.getvalue()
        assert "restricted_api" in log_output
        assert "researcher" in log_output
        assert "unauthorized" in log_output.lower() or "not authorized" in log_output.lower()
    finally:
        logger.removeHandler(handler)
