"""Stripe API tool -- read-only for Phase 1."""

from __future__ import annotations

import logging
import time

import httpx

from .base import BaseTool, ToolResult
from .rate_limiter import integration_call

logger = logging.getLogger(__name__)


class StripeTool(BaseTool):  # type: ignore[override]
    name = "stripe_api"
    description = "Fetch Stripe revenue, charges, and customer data (read-only)"
    required_integrations = ["stripe"]

    async def execute(self, action: str, **kwargs) -> ToolResult:  # noqa: C901  # type: ignore[override]
        start = time.monotonic()

        api_key = kwargs.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"}

        async with httpx.AsyncClient(timeout=30.0) as client:

            async def _get(url: str, **request_kwargs) -> httpx.Response:
                return await integration_call(
                    "stripe",
                    client.get,
                    url,
                    **request_kwargs,
                )

            try:
                if action == "balance":
                    resp = await _get("https://api.stripe.com/v1/balance", headers=headers)
                    data = resp.json()
                    return ToolResult(
                        success=True,
                        data={
                            "available": data["available"][0]["amount"],
                            "pending": data["pending"][0]["amount"],
                        },
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                elif action == "charges":
                    resp = await _get(
                        "https://api.stripe.com/v1/charges",
                        headers=headers,
                        params={"limit": kwargs.get("limit", 20)},
                    )
                    charges = [
                        {
                            "id": c["id"],
                            "amount": c["amount"],
                            "currency": c["currency"],
                            "status": c["status"],
                            "created": c["created"],
                        }
                        for c in resp.json().get("data", [])
                    ]
                    return ToolResult(
                        success=True,
                        data={"charges": charges},
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                elif action == "customers":
                    resp = await _get(
                        "https://api.stripe.com/v1/customers",
                        headers=headers,
                        params={"limit": kwargs.get("limit", 20)},
                    )
                    customers = [
                        {"id": c["id"], "email": c.get("email"), "name": c.get("name")}
                        for c in resp.json().get("data", [])
                    ]
                    return ToolResult(
                        success=True,
                        data={"customers": customers},
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                else:
                    return ToolResult(
                        success=False,
                        error=f"Unknown action: {action}",
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

            except httpx.HTTPStatusError as exc:
                return ToolResult(
                    success=False,
                    error=f"HTTP {exc.response.status_code}",
                    latency_ms=(time.monotonic() - start) * 1000,
                )
            except Exception as exc:
                logger.exception("Stripe tool error")
                return ToolResult(
                    success=False, error=str(exc), latency_ms=(time.monotonic() - start) * 1000
                )

    async def validate_auth(self, token: str | None = None) -> bool:
        """Probe the user's real Stripe key against /v1/balance.

        Returns:
            True   -> 200 (token is valid)
            False  -> 401 (auth rejected) OR no token supplied OR network error

        Pre-fix: this used a literal "sk_test_placeholder" string and accepted
        both 200 and 401 as success, so it could never report bad credentials.
        """
        if not token:
            return False
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await integration_call(
                    "stripe",
                    client.get,
                    "https://api.stripe.com/v1/balance",
                    headers={"Authorization": f"Bearer {token}"},
                )
                return resp.status_code == 200
            except Exception as exc:
                logger.warning("Stripe validate_auth failed: %s", exc)
                return False
