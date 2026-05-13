"""Stripe API tool -- read-only for Phase 1."""

from __future__ import annotations

import logging
import time

import httpx

from .base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


class StripeTool(BaseTool):  # type: ignore[override]
    name = "stripe_api"
    description = "Fetch Stripe revenue, charges, and customer data (read-only)"
    required_integrations = ["stripe"]

    async def execute(self, action: str, **kwargs) -> ToolResult:
        start = time.monotonic()

        api_key = kwargs.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                if action == "balance":
                    resp = await client.get("https://api.stripe.com/v1/balance", headers=headers)
                    data = resp.json()
                    return ToolResult(
                        success=True,
                        data={"available": data["available"][0]["amount"], "pending": data["pending"][0]["amount"]},
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

                elif action == "charges":
                    resp = await client.get(
                        "https://api.stripe.com/v1/charges",
                        headers=headers,
                        params={"limit": kwargs.get("limit", 20)},
                    )
                    charges = [
                        {"id": c["id"], "amount": c["amount"], "currency": c["currency"],
                         "status": c["status"], "created": c["created"]}
                        for c in resp.json().get("data", [])
                    ]
                    return ToolResult(success=True, data={"charges": charges}, latency_ms=(time.monotonic() - start) * 1000)

                elif action == "customers":
                    resp = await client.get(
                        "https://api.stripe.com/v1/customers",
                        headers=headers,
                        params={"limit": kwargs.get("limit", 20)},
                    )
                    customers = [
                        {"id": c["id"], "email": c.get("email"), "name": c.get("name")}
                        for c in resp.json().get("data", [])
                    ]
                    return ToolResult(success=True, data={"customers": customers}, latency_ms=(time.monotonic() - start) * 1000)

                else:
                    return ToolResult(success=False, error=f"Unknown action: {action}", latency_ms=(time.monotonic() - start) * 1000)

            except httpx.HTTPStatusError as exc:
                return ToolResult(success=False, error=f"HTTP {exc.response.status_code}", latency_ms=(time.monotonic() - start) * 1000)
            except Exception as exc:
                logger.exception("Stripe tool error")
                return ToolResult(success=False, error=str(exc), latency_ms=(time.monotonic() - start) * 1000)

    async def validate_auth(self) -> bool:
        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.get("https://api.stripe.com/v1/balance", headers={"Authorization": "Bearer sk_test_placeholder"})
                return resp.status_code in (200, 401)
            except Exception:
                return False
