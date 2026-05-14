"""Per-integration rate limiter using asyncio.Semaphore.

From SPEC.md Section 5.5.2 — integration_call() wraps all tool calls.
Each integration gets its own Semaphore to serialize concurrent calls.
Different integrations run in parallel.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

# Per-integration concurrency limits (SPEC.md Section 5.5.2)
INTEGRATION_LIMITS: dict[str, int] = {
    "github": 5,
    "stripe": 2,
    "gmail": 10,
    "linear": 5,
    # _default covers any integration not explicitly listed
    "_default": 20,
}


class IntegrationRateLimiter:
    """Per-integration rate limiter using asyncio.Semaphore per key.

    Usage:
        limiter = IntegrationRateLimiter()
        result = await limiter.integration_call("github", my_async_fn, arg1, kwarg=value)

        # Most production tool code should use the module-level wrapper instead:
        result = await integration_call("github", my_async_fn, arg1, kwarg=value)

    Concurrent calls to the SAME integration are serialized by a shared Semaphore.
    Calls to DIFFERENT integrations run in parallel.
    """

    def __init__(self, limits: dict[str, int] | None = None) -> None:
        self._limits = limits or INTEGRATION_LIMITS
        self._semaphores: dict[str, asyncio.Semaphore] = {
            key: asyncio.Semaphore(limit) for key, limit in self._limits.items()
        }
        # Ensure _default always exists
        if "_default" not in self._semaphores:
            self._semaphores["_default"] = asyncio.Semaphore(self._limits.get("_default", 20))

    def _get_semaphore(self, integration: str) -> asyncio.Semaphore:
        """Return the Semaphore for this integration, falling back to _default."""
        return self._semaphores.get(integration, self._semaphores["_default"])

    async def integration_call(
        self,
        integration: str,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run fn with rate limiting for the given integration.

        Serializes concurrent calls to the same integration using a Semaphore.
        Returns the result of fn.
        """
        semaphore = self._get_semaphore(integration)
        async with semaphore:
            return await fn(*args, **kwargs)


DEFAULT_RATE_LIMITER = IntegrationRateLimiter()


async def integration_call(
    integration: str,
    fn: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Run fn through the process-wide per-integration rate limiter.

    This is the production wrapper expected by SPEC.md §5.5.2. A module-level
    limiter ensures GitHub, Stripe, Gmail/IMAP, Linear, and future tools share
    one semaphore set within the API process instead of each file creating an
    independent limiter.
    """
    return await DEFAULT_RATE_LIMITER.integration_call(integration, fn, *args, **kwargs)
