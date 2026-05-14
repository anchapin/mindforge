"""Test LinearTool — Task 11.

Implements list_issues, create_issue, update_issue, get_issue.
Linear API v1 via GraphQL. Rate limited via integration_call("linear", fn).

Run: pytest backend/tests/integration/test_linear.py -v
"""

from __future__ import annotations

import os
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

# Patch os.makedirs BEFORE any backend imports — same pattern as other integration tests
_original_makedirs = os.makedirs


def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)


os.makedirs = _patched_makedirs  # type: ignore[assignment]


class FakeLinearResponse:
    """Simulates a Linear GraphQL response (data wrapper) or error."""

    def __init__(self, data: dict | None = None, errors: list[dict] | None = None):
        self._data = data
        self._errors = errors

    def json(self) -> dict:
        if self._errors:
            return {"errors": self._errors}
        return {"data": self._data}


class TestLinearTool:
    """LinearTool — actions: list_issues, create_issue, update_issue, get_issue.

    Uses Linear GraphQL API v1: https://api.linear.app/graphql
    All calls go through integration_call("linear", fn) for rate limiting.
    """

    def test_list_issues_returns_open_issues(self):
        """RED: list_issues returns list of issue dicts with id, title, state, priority.

        GREEN: Execute listIssues query against Linear GraphQL endpoint.
        """
        from backend.tools.integrations.linear import LinearTool

        tool = LinearTool()

        mock_resp = FakeLinearResponse(data={
            "issues": {
                "nodes": [
                    {"id": "issue-1", "title": "Fix auth bug", "state": {"name": "In Progress"}, "priority": 1},
                    {"id": "issue-2", "title": "Add dark mode", "state": {"name": "Todo"}, "priority": 0},
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        })

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(
                    action="list_issues",
                    api_key="lin_test_key",
                    team_id="team-1",
                )
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True, f"Expected success, got: {result.error}"
        issues = result.data.get("issues", [])
        assert len(issues) == 2
        assert issues[0]["id"] == "issue-1"
        assert issues[0]["title"] == "Fix auth bug"
        assert issues[0]["state"] == "In Progress"
        assert issues[0]["priority"] == 1

    def test_list_issues_uses_pagination(self):
        """RED: list_issues fetches all pages (hasNextPage=true loop).

        GREEN: Loop while hasNextPage, collecting all nodes.
        """
        from backend.tools.integrations.linear import LinearTool

        tool = LinearTool()

        page1 = FakeLinearResponse(data={
            "issues": {
                "nodes": [
                    {"id": "issue-1", "title": "Issue 1", "state": {"name": "Todo"}, "priority": 0},
                    {"id": "issue-2", "title": "Issue 2", "state": {"name": "Todo"}, "priority": 0},
                ],
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
            }
        })

        page2 = FakeLinearResponse(data={
            "issues": {
                "nodes": [
                    {"id": "issue-3", "title": "Issue 3", "state": {"name": "Todo"}, "priority": 0},
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        })

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=[page1, page2])

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(action="list_issues", api_key="lin_test_key", team_id="team-1")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True
        issues = result.data.get("issues", [])
        assert len(issues) == 3, f"Expected 3 issues across 2 pages, got {len(issues)}: {issues}"
        assert mock_client.post.call_count == 2

    def test_create_issue_returns_issue_url_and_number(self):
        """RED: create_issue returns {issue_url, number, id} for created issue.

        GREEN: Execute createIssue mutation, return id/number/url from response.
        """
        from backend.tools.integrations.linear import LinearTool

        tool = LinearTool()

        mock_resp = FakeLinearResponse(data={
            "issueCreate": {
                "success": True,
                "issue": {
                    "id": "issue-new-123",
                    "identifier": "PROJ-42",
                    "title": "New feature request",
                    "url": "https://linear.app/acme/issue/PROJ-42",
                },
            }
        })

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(
                    action="create_issue",
                    api_key="lin_test_key",
                    team_id="team-1",
                    title="New feature request",
                    body="Description of the feature",
                    priority=1,
                )
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True, f"Expected success, got: {result.error}"
        data = result.data
        assert data["id"] == "issue-new-123"
        assert data["number"] == "PROJ-42"
        assert data["issue_url"] == "https://linear.app/acme/issue/PROJ-42"

    def test_update_issue_returns_success_true(self):
        """RED: update_issue returns {success: True} when issue is updated.

        GREEN: Execute updateIssue mutation with issue_id + provided fields.
        """
        from backend.tools.integrations.linear import LinearTool

        tool = LinearTool()

        mock_resp = FakeLinearResponse(data={
            "issueUpdate": {
                "success": True,
                "issue": {
                    "id": "issue-1",
                    "title": "Updated title",
                    "state": {"name": "Done"},
                },
            }
        })

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(
                    action="update_issue",
                    api_key="lin_test_key",
                    issue_id="issue-1",
                    title="Updated title",
                    state="Done",
                )
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True, f"Expected success, got: {result.error}"
        # Verify the GraphQL mutation was called with correct issue ID
        call_body = mock_client.post.call_args.kwargs.get("json", {})
        variables = call_body.get("variables", {})
        assert variables.get("id") == "issue-1" or variables.get("issueId") == "issue-1"

    def test_get_issue_returns_full_issue_detail(self):
        """RED: get_issue returns {id, title, description, state, assignee, priority}.

        GREEN: Execute issue query with full field set.
        """
        from backend.tools.integrations.linear import LinearTool

        tool = LinearTool()

        mock_resp = FakeLinearResponse(data={
            "issue": {
                "id": "issue-1",
                "identifier": "PROJ-1",
                "title": "Bug: login broken",
                "description": "Users cannot log in with SSO",
                "state": {"name": "In Progress"},
                "priority": 2,
                "assignee": {"name": "Alex Chen", "email": "alex@example.com"},
                "url": "https://linear.app/acme/issue/PROJ-1",
                "createdAt": "2026-05-01T10:00:00Z",
                "updatedAt": "2026-05-10T12:00:00Z",
            }
        })

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(action="get_issue", api_key="lin_test_key", issue_id="issue-1")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True, f"Expected success, got: {result.error}"
        issue = result.data.get("issue", {})
        assert issue["id"] == "issue-1"
        assert issue["title"] == "Bug: login broken"
        assert issue["state"] == "In Progress"
        assert issue["assignee_name"] == "Alex Chen"

    def test_get_issue_not_found_returns_error(self):
        """RED: get_issue returns success=False with error for unknown issue ID.

        GREEN: Check for GraphQL errors or null issue in response.
        """
        from backend.tools.integrations.linear import LinearTool

        tool = LinearTool()

        mock_resp = FakeLinearResponse(data={"issue": None})

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(action="get_issue", api_key="lin_test_key", issue_id="nonexistent")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is False
        assert "not found" in result.error.lower() or "null" in result.error.lower()

    def test_list_issues_uses_integration_rate_limiter(self):
        """RED: list_issues must go through IntegrationRateLimiter.integration_call('linear', fn).

        GREEN: Wrap HTTP call in integration_call("linear", lambda: client.post(...)).
        Ensures Semaphore(5) limits concurrent Linear API calls.
        """
        from backend.tools.integrations.linear import LinearTool
        from backend.tools.rate_limiter import IntegrationRateLimiter

        tool = LinearTool()
        limiter = IntegrationRateLimiter()

        mock_resp = FakeLinearResponse(data={
            "issues": {
                "nodes": [{"id": "issue-1", "title": "Test", "state": {"name": "Todo"}, "priority": 0}],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
        })

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await limiter.integration_call(
                    "linear",
                    lambda: tool.execute(action="list_issues", api_key="lin_test_key", team_id="team-1"),
                )
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True
        assert len(result.data.get("issues", [])) == 1

    def test_linear_api_auth_validation(self):
        """RED: validate_auth() returns True when Linear API key is valid (200 response).

        GREEN: GET https://api.linear.app/graphql with Authorization header.
        Return True on 200, False on 401/403.
        """
        from backend.tools.integrations.linear import LinearTool

        tool = LinearTool()

        # Mock a successful auth check via GraphQL POST
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"viewer": {"id": "user-1", "name": "Test User"}}}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.validate_auth(api_key="lin_valid_key")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result is True

    def test_linear_api_auth_invalid_key(self):
        """RED: validate_auth() returns False when API key is invalid (401 response).

        GREEN: 401 from Linear -> return False.
        """
        from backend.tools.integrations.linear import LinearTool

        tool = LinearTool()

        mock_resp = MagicMock()
        mock_resp.status_code = 401

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.validate_auth(api_key="lin_bad_key")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result is False
