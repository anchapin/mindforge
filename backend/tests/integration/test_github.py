"""Test GitHub get_commits pagination and date filtering — Task 14.

Run: pytest backend/tests/integration/test_github.py -v
"""

from __future__ import annotations

import os
import pathlib
from datetime import UTC, datetime
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


class TestGetCommitsPagination:
    """get_commits() must paginate through all pages until since date reached."""

    def test_get_commits_single_page(self):
        """RED: Single page of commits is returned as list of dicts.

        Current github.py action="commits" returns commits without pagination or
        since filtering. After implementation: should return list of commit dicts
        with sha (7 chars), message (first line), author, date.
        """
        from backend.tools.github import GitHubTool

        tool = GitHubTool()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "sha": "abc1234abcd5678efgh9012",
                "commit": {
                    "message": "Fix authentication bug\nDetailed description",
                    "author": {"name": "Alex Chen", "date": "2026-05-01T10:00:00Z"},
                },
            },
            {
                "sha": "def4567hijk8901lmno1234",
                "commit": {
                    "message": "Add new feature: user dashboard",
                    "author": {"name": "Alex Chen", "date": "2026-05-03T14:30:00Z"},
                },
            },
        ]
        mock_resp.headers = {}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(action="commits", token="ghp_test", repo="test/repo")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True, f"Expected success, got: {result.error}"
        commits = result.data.get("commits", [])
        assert len(commits) == 2
        assert commits[0]["sha"] == "abc1234"  # 7 chars
        assert commits[0]["message"] == "Fix authentication bug"
        assert commits[0]["author"] == "Alex Chen"
        assert commits[0]["date"] == "2026-05-01T10:00:00Z"

    def test_get_commits_paginates_through_multiple_pages(self):
        """RED: get_commits() paginates until no 'next' Link header.

        GREEN: Loop with Link header parsing; stop when no rel="next".
        Current code fetches one page only. After: fetch all pages.
        """
        from backend.tools.github import GitHubTool

        tool = GitHubTool()

        # Page 1
        page1_resp = MagicMock()
        page1_resp.status_code = 200
        page1_resp.json.return_value = [
            {"sha": "aaa0001aaaa", "commit": {"message": "Commit 1", "author": {"name": "Alex", "date": "2026-05-01T00:00:00Z"}}},
            {"sha": "aaa0002bbbb", "commit": {"message": "Commit 2", "author": {"name": "Alex", "date": "2026-05-02T00:00:00Z"}}},
        ]
        page1_resp.headers = {
            "Link": '<https://api.github.com/repos/test/repo/commits?page=2>; rel="next", <https://api.github.com/repos/test/repo/commits?page=3>; rel="last"'
        }

        # Page 2
        page2_resp = MagicMock()
        page2_resp.status_code = 200
        page2_resp.json.return_value = [
            {"sha": "bbb0001cccc", "commit": {"message": "Commit 3", "author": {"name": "Alex", "date": "2026-05-03T00:00:00Z"}}},
            {"sha": "bbb0002dddd", "commit": {"message": "Commit 4", "author": {"name": "Alex", "date": "2026-05-04T00:00:00Z"}}},
        ]
        page2_resp.headers = {
            "Link": '<https://api.github.com/repos/test/repo/commits?page=3>; rel="next", <https://api.github.com/repos/test/repo/commits?page=3>; rel="last"'
        }

        # Page 3 (last — no "next")
        page3_resp = MagicMock()
        page3_resp.status_code = 200
        page3_resp.json.return_value = [
            {"sha": "ccc0001eeee", "commit": {"message": "Commit 5", "author": {"name": "Alex", "date": "2026-05-05T00:00:00Z"}}},
        ]
        page3_resp.headers = {}  # No next page

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=[page1_resp, page2_resp, page3_resp])

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(action="commits", token="ghp_test", repo="test/repo")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True, f"Expected success, got: {result.error}"
        commits = result.data.get("commits", [])
        assert len(commits) == 5, f"Expected 5 commits (3 pages), got {len(commits)}: {commits}"
        assert commits[0]["sha"] == "aaa0001"
        assert commits[4]["sha"] == "ccc0001"

    def test_get_commits_uses_per_page_100(self):
        """RED: get_commits must request per_page=100 for efficiency.

        GREEN: params={"per_page": 100} on GitHub API calls.
        Current code uses per_page=30 (default).
        """
        from backend.tools.github import GitHubTool

        tool = GitHubTool()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_resp.headers = {}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(action="commits", token="ghp_test", repo="test/repo")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True
        # Verify the request was made with per_page=100
        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args.kwargs
        assert "params" in call_kwargs, f"Expected 'params' in call kwargs, got: {call_kwargs}"
        assert call_kwargs["params"]["per_page"] == 100, f"Expected per_page=100, got: {call_kwargs['params']}"

    def test_get_commits_stops_at_since_date(self):
        """RED: Commits older than since=YYYY-MM-DD are excluded; pagination stops.

        GREEN: Parse ?since=YYYY-MM-DD param. On each page, check oldest commit date.
        If oldest commit date < since threshold, discard older commits and stop fetching.
        """
        from backend.tools.github import GitHubTool

        tool = GitHubTool()

        # Page 1: contains commits on both sides of the since threshold (2026-05-05)
        page1_resp = MagicMock()
        page1_resp.status_code = 200
        page1_resp.json.return_value = [
            {"sha": "abc0001", "commit": {"message": "New commit 2026-05-10", "author": {"name": "Alex", "date": "2026-05-10T00:00:00Z"}}},
            {"sha": "abc0002", "commit": {"message": "Older commit 2026-05-01", "author": {"name": "Alex", "date": "2026-05-01T00:00:00Z"}}},
        ]
        # This page has a "next" but we should stop because oldest commit is before since
        page1_resp.headers = {
            "Link": '<https://api.github.com/repos/test/repo/commits?page=2>; rel="next", <https://api.github.com/repos/test/repo/commits?page=3>; rel="last"'
        }

        # Page 2: would have more old commits (should NOT be fetched)
        page2_resp = MagicMock()
        page2_resp.status_code = 200
        page2_resp.json.return_value = [
            {"sha": "abc0003", "commit": {"message": "Too old commit 2026-04-15", "author": {"name": "Alex", "date": "2026-04-15T00:00:00Z"}}},
        ]
        page2_resp.headers = {}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=[page1_resp, page2_resp])

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                # since=2026-05-05 — discard commits before this date, stop pagination
                return await tool.execute(action="commits", token="ghp_test", repo="test/repo", since="2026-05-05")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True, f"Expected success, got: {result.error}"
        commits = result.data.get("commits", [])
        # Should include the new commit (2026-05-10 >= 2026-05-05) but NOT the old one (2026-05-01 < 2026-05-05)
        # And should NOT have fetched page2
        assert len(commits) == 1, f"Expected 1 commit (after since filter), got {len(commits)}: {commits}"
        assert commits[0]["sha"] == "abc0001"
        # Only 1 HTTP call should have been made (page1 fetched, page2 NOT fetched because stop condition)
        assert mock_client.get.call_count == 1, f"Expected 1 HTTP call, got {mock_client.get.call_count}"


class TestGetCommitsRateLimitHandling:
    """GitHub API rate limit (403) must be handled gracefully."""

    def test_get_commits_respects_rate_limit_403(self):
        """RED: HTTP 403 from GitHub returns error with rate limit info.

        GREEN: Catch HTTPStatusError 403, return ToolResult with error including
        rate limit reset time if available.
        """
        from backend.tools.github import GitHubTool

        tool = GitHubTool()

        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = "rate limit exceeded"
        mock_resp.headers = {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(int(datetime.now(UTC).timestamp()) + 3600),
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await tool.execute(action="commits", token="ghp_test", repo="test/repo")
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is False
        assert "403" in result.error or "rate limit" in result.error.lower()

    def test_get_commits_integration_rate_limiter_used(self):
        """RED: get_commits must go through IntegrationRateLimiter.integration_call('github', fn).

        GREEN: Wrap HTTP call in integration_call("github", lambda: ...).
        This ensures the per-integration Semaphore(5) is respected.
        """
        from backend.tools.github import GitHubTool
        from backend.tools.rate_limiter import IntegrationRateLimiter

        tool = GitHubTool()
        limiter = IntegrationRateLimiter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"sha": "test1234abcd", "commit": {"message": "Test commit", "author": {"name": "Alex", "date": "2026-05-01T00:00:00Z"}}},
        ]
        mock_resp.headers = {}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            import asyncio
            async def run():
                return await limiter.integration_call(
                    "github",
                    lambda: tool.execute(action="commits", token="ghp_test", repo="test/repo"),
                )
            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.success is True
        assert len(result.data.get("commits", [])) == 1
