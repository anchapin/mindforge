"""Test per-integration rate limiter — Issue #19.

Tests:
1. IntegrationRateLimiter serializes concurrent calls to the same integration
2. Different integrations run in parallel
3. Concurrent calls beyond limit are queued

Run: pytest backend/tests/integration/test_rate_limiter.py -v
"""

import asyncio
import os
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch os.makedirs BEFORE any backend imports
_original_makedirs = os.makedirs


def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)


os.makedirs = _patched_makedirs  # type: ignore[assignment]


class TestIntegrationRateLimiter:
    """Verify per-integration rate limiting with asyncio.Semaphore."""

    @pytest.mark.asyncio
    async def test_rate_limiter_serializes_concurrent_github_calls(self):
        """6 concurrent GitHub calls → 5 pass immediately, 6th is queued and completes after.

        RED: FAILS - no rate limiter exists, all 6 calls start immediately (no serialization).
        GREEN: IntegrationRateLimiter with Semaphore(5) for github, 6th call waits for slot.
        """
        from backend.tools.rate_limiter import IntegrationRateLimiter

        limiter = IntegrationRateLimiter()

        call_log: list[tuple[str, float]] = []
        active_count = 0
        max_concurrent = 0

        async def mock_github_call(call_id: int):
            nonlocal active_count, max_concurrent
            entry_time = asyncio.get_event_loop().time()

            # The wrapper function to be rate-limited
            async def rate_limited_fn():
                nonlocal active_count, max_concurrent
                active_count += 1
                max_concurrent = max(max_concurrent, active_count)
                call_log.append(("enter", entry_time))
                await asyncio.sleep(0.05)
                active_count -= 1
                call_log.append(("exit", asyncio.get_event_loop().time()))

            await limiter.integration_call("github", rate_limited_fn)

        # Launch 6 concurrent github calls
        await asyncio.gather(*[mock_github_call(i) for i in range(6)])

        # With Semaphore(5), max_concurrent should be 5, not 6
        assert max_concurrent == 5, (
            f"Expected max 5 concurrent github calls, got {max_concurrent}. "
            f"Rate limiter should serialize beyond limit."
        )

    @pytest.mark.asyncio
    async def test_different_integrations_run_in_parallel(self):
        """Concurrent calls to different integrations (github vs stripe) should NOT block each other.

        GREEN: Passes because IntegrationRateLimiter is keyed per-integration.
        """
        from backend.tools.rate_limiter import IntegrationRateLimiter

        limiter = IntegrationRateLimiter()

        async def mock_github():
            async def rate_limited_fn():
                await asyncio.sleep(0.2)
                return "github"

            return await limiter.integration_call("github", rate_limited_fn)

        async def mock_stripe():
            async def rate_limited_fn():
                await asyncio.sleep(0.1)
                return "stripe"

            return await limiter.integration_call("stripe", rate_limited_fn)

        # Both start simultaneously; stripe should finish before github
        # because they're different integrations and should run in parallel
        import time

        start = time.monotonic()
        results = await asyncio.gather(mock_github(), mock_stripe())
        elapsed = time.monotonic() - start

        # With parallel execution, should take ~0.2s (max of 0.2, 0.1)
        # Without parallel (serial), would take ~0.3s (0.2 + 0.1)
        assert elapsed < 0.28, (
            f"Different integrations took {elapsed:.2f}s (expected <0.28s for parallel). "
            f"Rate limiter may be blocking across different integrations."
        )
        assert results == ["github", "stripe"]

    @pytest.mark.asyncio
    async def test_rate_limiter_default_limit(self):
        """Unknown integration should use _default Semaphore(20).

        GREEN: Passes because _default exists and is Semaphore(20).
        """
        from backend.tools.rate_limiter import IntegrationRateLimiter

        limiter = IntegrationRateLimiter()

        async def mock_unknown():
            async def rate_limited_fn():
                await asyncio.sleep(0.01)
                return "ok"

            return await limiter.integration_call("unknown_integration", rate_limited_fn)

        results = await asyncio.gather(*[mock_unknown() for _ in range(5)])
        assert all(r == "ok" for r in results)

    @pytest.mark.asyncio
    async def test_rate_limiter_preserves_return_value(self):
        """integration_call should return the result of the wrapped function.

        GREEN: Passes — the wrapper just needs to pass through the return value.
        """
        from backend.tools.rate_limiter import IntegrationRateLimiter

        limiter = IntegrationRateLimiter()

        async def mock_fn():
            await asyncio.sleep(0.01)
            return "result_value"

        result = await limiter.integration_call("test", mock_fn)
        assert result == "result_value"


class TestToolRateLimiterWiring:
    """Verify production tools route outbound calls through shared integration_call."""

    @pytest.mark.asyncio
    async def test_module_level_integration_call_uses_shared_limiter(self):
        """SPEC §5.5.2 expects a process-wide integration_call wrapper."""
        from backend.tools import rate_limiter

        calls: list[tuple[str, tuple, dict]] = []
        original = rate_limiter.DEFAULT_RATE_LIMITER.integration_call

        async def tracking_call(integration: str, fn, *args, **kwargs):
            calls.append((integration, args, kwargs))
            return await fn(*args, **kwargs)

        rate_limiter.DEFAULT_RATE_LIMITER.integration_call = tracking_call  # type: ignore[method-assign]
        try:

            async def sample(value: str) -> str:
                return f"ok:{value}"

            result = await rate_limiter.integration_call("github", sample, "test")
        finally:
            rate_limiter.DEFAULT_RATE_LIMITER.integration_call = original  # type: ignore[method-assign]

        assert result == "ok:test"
        assert calls == [("github", ("test",), {})]

    @pytest.mark.asyncio
    async def test_github_tool_routes_api_calls_through_rate_limiter(self):
        from backend.tools.github import GitHubTool

        calls: list[str] = []

        async def tracking_call(integration: str, fn, *args, **kwargs):
            calls.append(integration)
            return await fn(*args, **kwargs)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {
                "sha": "abc1234abcd",
                "commit": {
                    "message": "Commit through limiter",
                    "author": {"name": "Alex", "date": "2026-05-01T00:00:00Z"},
                },
            }
        ]
        mock_resp.headers = {}

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("backend.tools.github.integration_call", side_effect=tracking_call),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await GitHubTool().execute(
                action="commits", token="ghp_test", repo="test/repo"
            )

        assert result.success is True
        assert calls == ["github"]

    @pytest.mark.asyncio
    async def test_stripe_tool_routes_api_calls_through_rate_limiter(self):
        from backend.tools.stripe import StripeTool

        calls: list[str] = []

        async def tracking_call(integration: str, fn, *args, **kwargs):
            calls.append(integration)
            return await fn(*args, **kwargs)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "available": [{"amount": 1000}],
            "pending": [{"amount": 250}],
        }

        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("backend.tools.stripe.integration_call", side_effect=tracking_call),
            patch("httpx.AsyncClient", return_value=mock_client),
        ):
            result = await StripeTool().execute(action="balance", api_key="sk_test")

        assert result.success is True
        assert calls == ["stripe"]

    @pytest.mark.asyncio
    async def test_email_fetch_tool_routes_imap_work_through_gmail_rate_limiter(self):
        from backend.tools.base import ToolResult
        from backend.tools.email_fetch import EmailFetchTool

        calls: list[str] = []

        async def tracking_call(integration: str, fn, *args, **kwargs):
            calls.append(integration)
            return ToolResult(success=True, data={"emails": []}, latency_ms=0)

        with patch("backend.tools.email_fetch.integration_call", side_effect=tracking_call):
            result = await EmailFetchTool().execute(
                action="recent",
                host="imap.gmail.com",
                username="user@example.com",
                password="app-password",
            )

        assert result.success is True
        assert calls == ["gmail"]

    @pytest.mark.asyncio
    async def test_linear_tool_uses_shared_rate_limiter_wrapper(self):
        from backend.tools.integrations.linear import LinearTool

        calls: list[str] = []

        async def tracking_call(integration: str, fn, *args, **kwargs):
            calls.append(integration)
            return {
                "data": {
                    "issue": {
                        "id": "lin_123",
                        "identifier": "MF-1",
                        "title": "Linear through limiter",
                    }
                }
            }

        with patch("backend.tools.integrations.linear.integration_call", side_effect=tracking_call):
            result = await LinearTool().execute(
                action="get_issue", api_key="lin_test", issue_id="lin_123"
            )

        assert result.success is True
        assert calls == ["linear"]
