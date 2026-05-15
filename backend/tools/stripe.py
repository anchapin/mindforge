"""Stripe API tool -- read-only for Phase 1."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .base import BaseTool, ToolResult
from .rate_limiter import integration_call

logger = logging.getLogger(__name__)


class StripeTool(BaseTool):  # type: ignore[override]
    name = "stripe_api"
    description = "Stripe API: fetch revenue/charges/customers; issue refunds (refund is high-stakes — requires_approval must be true)"
    required_integrations = ["stripe"]

    async def execute(self, action: str, agent_role: str | None = None, **kwargs) -> ToolResult:  # noqa: C901  # type: ignore[override]
        start = time.monotonic()

        # Permission enforcement — block unauthorized agents before any API call
        if agent_role is not None:
            self.check_permissions(agent_role, action)

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

            async def _post(url: str, **request_kwargs) -> httpx.Response:
                return await integration_call(
                    "stripe",
                    client.post,
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

                elif action == "refund":
                    # Issue a refund. HIGH-STAKES — the calling skill MUST set
                    # requires_approval: true. The supervisor's
                    # _HIGH_STAKES_ACTIONS set already lists "stripe_api.refund"
                    # so memory-dominated proposals trigger the approval gate.
                    charge_id = kwargs.get("charge_id")
                    if not charge_id:
                        return ToolResult(
                            success=False,
                            error="refund requires charge_id",
                            latency_ms=(time.monotonic() - start) * 1000,
                        )
                    # Stripe expects application/x-www-form-urlencoded for v1 API
                    body: dict[str, Any] = {"charge": charge_id}
                    amount = kwargs.get("amount")
                    if amount is not None:
                        body["amount"] = int(amount)  # cents; partial refund
                    reason = kwargs.get("reason")
                    if reason:
                        # Allowed values per Stripe API:
                        # duplicate, fraudulent, requested_by_customer
                        body["reason"] = str(reason)
                    metadata = kwargs.get("metadata") or {}
                    for k, v in metadata.items():
                        body[f"metadata[{k}]"] = str(v)

                    resp = await _post(
                        "https://api.stripe.com/v1/refunds",
                        headers={
                            **headers,
                            "Content-Type": "application/x-www-form-urlencoded",
                        },
                        data=body,
                    )
                    if resp.status_code >= 400:
                        return ToolResult(
                            success=False,
                            error=f"Stripe refund failed: HTTP {resp.status_code} {resp.text[:200]}",
                            latency_ms=(time.monotonic() - start) * 1000,
                        )
                    data = resp.json()
                    return ToolResult(
                        success=True,
                        data={
                            "id": data.get("id"),
                            "charge": data.get("charge"),
                            "amount": data.get("amount"),
                            "currency": data.get("currency"),
                            "status": data.get("status"),
                            "reason": data.get("reason"),
                            "created": data.get("created"),
                        },
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
