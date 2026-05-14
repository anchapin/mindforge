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
import sqlite3
import tempfile
from unittest.mock import patch

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