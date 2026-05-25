"""Unit tests for LinearTool — issue #153.

Phase 1 integration using Linear GraphQL API (https://api.linear.app/graphql).
Personal API token auth (not OAuth).

Post-PR contract:
  - name: linear_api
  - required_integrations: ["linear"]
  - Actions: list_issues, create_issue, update_issue, get_issue
  - validate_auth: returns True on 200, False on 401/error
  - All calls go through integration_call("linear", fn)
  - Rate limited via INTEGRATION_LIMITS["linear"] = 5
"""

from __future__ import annotations

import pytest

from backend.tools.integrations.linear import LinearTool
from backend.tools.registry import ToolRegistry, register_all_tools


@pytest.fixture(autouse=True)
def _clean_registry():
    ToolRegistry._tools.clear()
    yield
    ToolRegistry._tools.clear()


@pytest.fixture
def tool():
    return LinearTool()


# ---------------------------------------------------------------------------
# Tool metadata
# ---------------------------------------------------------------------------


def test_linear_tool_name_is_linear_api(tool):
    assert tool.name == "linear_api"


def test_linear_tool_description_is_set(tool):
    assert tool.description == "Manage Linear issues: list, create, update, get"


def test_linear_tool_required_integrations(tool):
    assert tool.required_integrations == ["linear"]


def test_linear_tool_registered_by_register_all_tools(_clean_registry):
    register_all_tools()
    assert "linear_api" in ToolRegistry.list_names()
    resolved = ToolRegistry.get("linear_api")
    assert resolved.name == "linear_api"


# ---------------------------------------------------------------------------
# Action routing
# ---------------------------------------------------------------------------


def test_linear_tool_rejects_unknown_action(tool):
    """Unknown actions return success=False with an error."""
    import asyncio

    async def run():
        return await tool.execute(action="not_a_real_action", api_key="test-key")

    result = asyncio.get_event_loop().run_until_complete(run())
    assert result.success is False
    assert "Unknown action" in result.error


def test_linear_tool_rejects_missing_api_key(tool):
    """No api_key returns success=False (not an exception)."""
    import asyncio

    async def run():
        return await tool.execute(action="list_issues", api_key="")

    result = asyncio.get_event_loop().run_until_complete(run())
    assert result.success is False


# ---------------------------------------------------------------------------
# validate_auth
# ---------------------------------------------------------------------------


def test_validate_auth_returns_false_for_empty_key(tool):
    import asyncio

    async def run():
        return await tool.validate_auth(token="")

    result = asyncio.get_event_loop().run_until_complete(run())
    assert result is False


def test_validate_auth_accepts_api_key_alias(tool):
    """validate_auth accepts api_key kwarg (Linear's own nomenclature)."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": {"viewer": {"id": "user-1"}}}

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("httpx.AsyncClient", return_value=mock_client):
        async def run():
            return await tool.validate_auth(api_key="lin_valid_key")

        result = asyncio.get_event_loop().run_until_complete(run())

    assert result is True


def test_validate_auth_returns_false_on_network_error(tool):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    import httpx

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        async def run():
            return await tool.validate_auth(token="lin_bad_key")

        result = asyncio.get_event_loop().run_until_complete(run())

    assert result is False


# ---------------------------------------------------------------------------
# _normalize_issue
# ---------------------------------------------------------------------------


def test_normalize_issue_handles_missing_fields(tool):
    """Missing assignee/state fields produce empty-string fallbacks."""
    raw = {"id": "issue-1", "title": "Test", "priority": 0}
    normalized = tool._normalize_issue(raw)
    assert normalized["assignee_name"] == ""
    assert normalized["assignee_email"] == ""
    assert normalized["state"] == ""
    assert normalized["description"] == ""


def test_normalize_issue_extracts_nested_state_and_assignee(tool):
    raw = {
        "id": "issue-1",
        "identifier": "PROJ-1",
        "title": "Fix bug",
        "description": "desc",
        "priority": 2,
        "url": "https://linear.app/proj/PROJ-1",
        "state": {"name": "In Progress"},
        "assignee": {"name": "Alice", "email": "alice@example.com"},
        "createdAt": "2026-05-01T10:00:00Z",
        "updatedAt": "2026-05-10T12:00:00Z",
    }
    normalized = tool._normalize_issue(raw)
    assert normalized["state"] == "In Progress"
    assert normalized["assignee_name"] == "Alice"
    assert normalized["assignee_email"] == "alice@example.com"
    assert normalized["identifier"] == "PROJ-1"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_execute_returns_error_on_httpx_network_error(tool):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    import httpx

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with patch("httpx.AsyncClient", return_value=mock_client):
        async def run():
            return await tool.execute(action="list_issues", api_key="test-key")

        result = asyncio.get_event_loop().run_until_complete(run())

    assert result.success is False
    assert "ConnectError" in result.error or "connection refused" in result.error
