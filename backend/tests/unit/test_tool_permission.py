"""Unit tests for tool permission enforcement (Issue #99)."""

from __future__ import annotations

import pytest
import asyncio

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

@pytest.mark.asyncio
async def test_custom_allowed_agents_restricts_access():
    """Custom integration_config with allowed_agents restricts access."""
    tool = DummyTool()
    result = await tool.execute("read", agent_identity="unknown", integration_config={"allowed_agents": ["engineer"]})
    assert result.success is False
    assert "not authorized" in result.error


# -------------------------------------------------------------------------------------------------
# Test: action-specific permission check (allowed_actions)
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_not_in_allowed_actions_returns_error():
    """When required action is not in allowed_actions, ToolResult returns success=False."""
    tool = WriteActionTool()
    # Integration allows only read actions, not 'send'
    result = await tool.execute(
        "send",
        agent_identity="cmo",
        integration_config={
            "allowed_agents": ["cmo"],
            "permissions": {"allowed_actions": ["read"]},  # no 'send'
        },
    )
    assert result.success is False
    assert "not granted" in result.error


@pytest.mark.asyncio
async def test_action_in_allowed_actions_succeeds():
    """When required action is in allowed_actions, execution proceeds."""
    tool = WriteActionTool()
    result = await tool.execute(
        "send",
        agent_identity="cmo",
        integration_config={
            "allowed_agents": ["cmo"],
            "permissions": {"allowed_actions": ["write_tool:send"]},
        },
    )
    assert result.success is True


# -------------------------------------------------------------------------------------------------
# Test: PermissionError propagated from execute_node (skill executor integration)
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthorized_agent_raises_permission_error_in_executor():
    """execute_node raises PermissionError when agent is not allowed for a tool."""
    from backend.skills.executor import execute_node
    from backend.skills.models import SkillNode, Skill, ExecutionGraph, SkillExecutionContext
    from datetime import datetime

    class FailingTool(BaseTool):
        name = "failing_tool"
        description = "A tool that should fail auth"
        required_integrations = ["github"]

        async def _execute(self, action: str, **kwargs) -> ToolResult:
            return ToolResult(success=True, data={}, tool_name=self.name)

        async def validate_auth(self, token: str | None = None) -> bool:
            return True

    tool = FailingTool()
    registry = type("MockRegistry", (), {"get": lambda self, n: tool if n == "failing_tool" else None})()

    node = SkillNode(id="test_node", agent="researcher", goal="Test node", tools=["failing_tool"])
    skill = Skill(
        id="test-skill",
        name="Test Skill",
        description="A test skill",
        category="test",
        agent_role="researcher",
        yaml_content="",
        version=1,
        tools=["failing_tool"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    ctx = SkillExecutionContext(
        task_id="test-task",
        skill=skill,
        node_id="test_node",
        scratch={},
        nodes_completed=[],
        started_at=datetime.utcnow(),
    )

    # researcher is NOT in allowed_agents -> node result is 'skipped' with error
    result = await execute_node(
        node=node,
        ctx=ctx,
        llm_complete=lambda prompt, system, agent_role: asyncio.sleep(0) or "result",
        tools=registry,
        agent_identity="researcher",
        integration_configs={
            "github": {
                "allowed_agents": ["engineer", "coo"],  # researcher NOT allowed
                "permissions": {},
            }
        },
    )
    assert result.status == "skipped"
    assert "not authorized" in result.error
    assert "failing_tool" in result.error


@pytest.mark.asyncio
async def test_authorized_agent_succeeds_in_executor():
    """execute_node allows execution when agent is in allowed_agents."""
    from backend.skills.executor import execute_node
    from backend.skills.models import SkillNode, Skill, ExecutionGraph, SkillExecutionContext
    from datetime import datetime

    class DummyToolForExecutor(BaseTool):
        name = "dummy_tool"
        description = "A test tool"
        required_integrations = ["github"]

        async def _execute(self, action: str, **kwargs) -> ToolResult:
            return ToolResult(success=True, data={"ok": True}, tool_name=self.name)

        async def validate_auth(self, token: str | None = None) -> bool:
            return True

    tool = DummyToolForExecutor()
    registry = type("MockRegistry", (), {"get": lambda self, n: tool if n == "dummy_tool" else None})()

    node = SkillNode(id="test_node", agent="engineer", goal="Test node", tools=["dummy_tool"])
    skill = Skill(
        id="test-skill",
        name="Test Skill",
        description="A test skill",
        category="test",
        agent_role="engineer",
        yaml_content="",
        version=1,
        tools=["dummy_tool"],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    ctx = SkillExecutionContext(
        task_id="test-task",
        skill=skill,
        node_id="test_node",
        scratch={},
        nodes_completed=[],
        started_at=datetime.utcnow(),
    )

    # engineer IS in allowed_agents -> should succeed
    result = await execute_node(
        node=node,
        ctx=ctx,
        llm_complete=lambda prompt, system, agent_role: asyncio.sleep(0) or "result",
        tools=registry,
        agent_identity="engineer",
        integration_configs={
            "github": {
                "allowed_agents": ["engineer", "coo"],
                "permissions": {},
            }
        },
    )
    assert result.status == "success"


# -------------------------------------------------------------------------------------------------
# Test: String-serialized JSON in allowed_agents and permissions is parsed
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_string_serialized_allowed_agents_parsed():
    """String-serialized JSON arrays in integration_config are parsed."""
    import json
    tool = RestrictedTool()
    result = await tool.execute(
        "read",
        agent_identity="researcher",
        integration_config={
            # Simulates how it comes from sqlite3 JSON columns
            "allowed_agents": json.dumps(["engineer", "coo"]),
            "permissions": json.dumps({}),
        },
    )
    assert result.success is False
    assert "not authorized" in result.error


# -------------------------------------------------------------------------------------------------
# Test: Empty allowed_agents blocks all agents
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_allowed_agents_blocks_all():
    """When allowed_agents is empty (block-all), no agent passes."""
    tool = RestrictedTool()
    result = await tool.execute(
        "read",
        agent_identity="coo",
        integration_config={"allowed_agents": [], "permissions": {}},
    )
    assert result.success is False
    assert "not authorized" in result.error


# -------------------------------------------------------------------------------------------------
# Test: Logging includes agent identity and action on permission denial
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unauthorized_error_message_includes_agent_identity(caplog):
    """Permission denial error message includes agent identity for auditability."""
    import logging
    tool = RestrictedTool()
    result = await tool.execute(
        "read",
        agent_identity="researcher",
        integration_config={"allowed_agents": ["engineer", "coo"], "permissions": {}},
    )
    assert result.success is False
    assert "researcher" in result.error
    assert "restricted_api" in result.error


# -------------------------------------------------------------------------------------------------
# Test: execute_skill passes agent_identity and integration_configs through DAG
# -------------------------------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_skill_passes_identity_and_configs_to_nodes():
    """execute_skill propagates agent_identity and integration_configs to _execute_dag."""
    from backend.skills.executor import execute_skill
    from backend.skills.models import Skill, ExecutionGraph, SkillNode
    from datetime import datetime
    from unittest.mock import AsyncMock, MagicMock

    calls: list[dict] = []

    async def mock_execute_node(node, ctx, llm_complete, tools, agent_identity=None, integration_configs=None):
        calls.append({
            "node_id": node.id,
            "agent_identity": agent_identity,
            "integration_configs": integration_configs,
        })
        from backend.skills.models import NodeResult
        return NodeResult(node_id=node.id, status="success", output={"text": "ok"})

    skill = Skill(
        id="test-skill",
        name="Test Skill",
        description="A test skill",
        category="test",
        agent_role="cmo",
        yaml_content="",
        version=1,
        tools=[],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        execution_graph=ExecutionGraph(
            nodes=[
                SkillNode(id="node1", agent="cmo", goal="Test node", tools=[]),
                SkillNode(id="node2", agent="cmo", goal="Test node 2", tools=[]),
            ],
            edges=[{"from": "node1", "to": "node2", "condition": "node1.success"}],
        ),
    )

    import pytest
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("backend.skills.executor.execute_node", mock_execute_node)
        result = await execute_skill(
            skill=skill,
            task_id="task-1",
            llm_complete=AsyncMock(),
            tools=MagicMock(),
            agent_identity="cmo",
            integration_configs={"github": {"allowed_agents": ["cmo"], "permissions": {}}},
        )

    assert len(calls) == 2
    assert calls[0]["agent_identity"] == "cmo"
    assert calls[0]["integration_configs"] == {"github": {"allowed_agents": ["cmo"], "permissions": {}}}
