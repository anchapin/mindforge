"""Integration tests for StripeTool action=refund (#43).

Mocks httpx.AsyncClient so no real Stripe call leaks. Verifies:
  - POST hits /v1/refunds with the correct form body
  - charge_id is required
  - amount/reason/metadata round-trip into the body
  - 4xx HTTP returns success=False with a useful error
  - high-stakes registration (supervisor will gate on this action)
  - subscription-refund.yaml uses the canonical tool name
"""

from __future__ import annotations

import pathlib

import httpx
import pytest

from backend.tools.stripe import StripeTool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code: int, json_body: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text or (str(json_body) if json_body else "")

    def json(self) -> dict:
        return self._json


class _CapturingClient:
    """Records POST calls + URL + headers + form body. Returns canned response."""

    last_url: str | None = None
    last_headers: dict | None = None
    last_data: dict | None = None
    last_method: str | None = None

    def __init__(self, response_or_exc):
        self._response_or_exc = response_or_exc

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, data=None, **kwargs):
        _CapturingClient.last_method = "POST"
        _CapturingClient.last_url = url
        _CapturingClient.last_headers = headers or {}
        _CapturingClient.last_data = data or {}
        if isinstance(self._response_or_exc, Exception):
            raise self._response_or_exc
        return self._response_or_exc

    async def get(self, *a, **kw):
        # Not exercised by refund tests; raise loudly if ever called
        raise RuntimeError("GET not expected for refund action")


@pytest.fixture(autouse=True)
def _bypass_rate_limiter(monkeypatch):
    async def _passthrough(_integration, fn, *args, **kwargs):
        return await fn(*args, **kwargs)

    monkeypatch.setattr("backend.tools.stripe.integration_call", _passthrough)


@pytest.fixture(autouse=True)
def _reset_capture():
    _CapturingClient.last_url = None
    _CapturingClient.last_headers = None
    _CapturingClient.last_data = None
    _CapturingClient.last_method = None
    yield


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestRefundHappyPath:
    @pytest.mark.asyncio
    async def test_full_refund(self, monkeypatch):
        canned = _FakeResp(
            200,
            {
                "id": "re_123",
                "charge": "ch_456",
                "amount": 1900,
                "currency": "usd",
                "status": "succeeded",
                "created": 1715000000,
            },
        )
        client = _CapturingClient(canned)
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", client)

        result = await StripeTool().execute(
            action="refund",
            api_key="sk_live_abc",
            charge_id="ch_456",
        )

        assert result.success
        assert result.data["id"] == "re_123"
        assert result.data["status"] == "succeeded"
        # Hit the right endpoint with form encoding
        assert _CapturingClient.last_url == "https://api.stripe.com/v1/refunds"
        assert _CapturingClient.last_method == "POST"
        assert (
            _CapturingClient.last_headers["Content-Type"]
            == "application/x-www-form-urlencoded"
        )
        # Bearer token reaches Stripe
        assert _CapturingClient.last_headers["Authorization"] == "Bearer sk_live_abc"
        # Body has charge id, no amount (=> full refund)
        assert _CapturingClient.last_data == {"charge": "ch_456"}

    @pytest.mark.asyncio
    async def test_partial_refund_with_amount_and_reason(self, monkeypatch):
        client = _CapturingClient(
            _FakeResp(200, {"id": "re_p", "charge": "ch_x", "amount": 500, "status": "succeeded"})
        )
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", client)

        await StripeTool().execute(
            action="refund",
            api_key="sk_live_abc",
            charge_id="ch_x",
            amount=500,
            reason="requested_by_customer",
        )
        body = _CapturingClient.last_data
        assert body["charge"] == "ch_x"
        assert body["amount"] == 500
        assert body["reason"] == "requested_by_customer"

    @pytest.mark.asyncio
    async def test_metadata_round_trips_into_form_body(self, monkeypatch):
        client = _CapturingClient(_FakeResp(200, {"id": "re_m", "status": "succeeded"}))
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", client)

        await StripeTool().execute(
            action="refund",
            api_key="sk_live_abc",
            charge_id="ch_m",
            metadata={"order_id": "ORD-42", "reason_text": "user requested"},
        )
        body = _CapturingClient.last_data
        # Stripe's flat-form metadata syntax
        assert body["metadata[order_id]"] == "ORD-42"
        assert body["metadata[reason_text]"] == "user requested"


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestRefundErrors:
    @pytest.mark.asyncio
    async def test_missing_charge_id(self, monkeypatch):
        client = _CapturingClient(_FakeResp(200, {}))
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", client)

        result = await StripeTool().execute(
            action="refund", api_key="sk_live_abc"
        )
        assert result.success is False
        assert "charge_id" in result.error
        # Did NOT hit the API
        assert _CapturingClient.last_url is None

    @pytest.mark.asyncio
    async def test_4xx_returns_failure(self, monkeypatch):
        client = _CapturingClient(
            _FakeResp(
                400,
                json_body={"error": {"message": "No such charge", "type": "invalid_request"}},
                text='{"error": {"message": "No such charge"}}',
            )
        )
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", client)

        result = await StripeTool().execute(
            action="refund", api_key="sk_live_abc", charge_id="ch_missing"
        )
        assert result.success is False
        assert "HTTP 400" in result.error

    @pytest.mark.asyncio
    async def test_network_error_returns_failure(self, monkeypatch):
        client = _CapturingClient(httpx.ConnectError("network down"))
        monkeypatch.setattr("backend.tools.stripe.httpx.AsyncClient", client)

        result = await StripeTool().execute(
            action="refund", api_key="sk_live_abc", charge_id="ch_x"
        )
        assert result.success is False


# ---------------------------------------------------------------------------
# High-stakes wiring + YAML
# ---------------------------------------------------------------------------


class TestHighStakesAndYaml:
    def test_refund_action_is_high_stakes(self):
        from backend.agents.supervisor import _HIGH_STAKES_ACTIONS

        # Either the dotted form (canonical) OR the legacy "stripe_refund"
        assert (
            "stripe_api.refund" in _HIGH_STAKES_ACTIONS
            or "stripe_refund" in _HIGH_STAKES_ACTIONS
        )

    def test_subscription_refund_yaml_uses_canonical_tool_name(self):
        """The YAML must reference `stripe_api` (not `stripe_refund_api`) so
        ToolRegistry.get() resolves at runtime."""
        yaml_path = (
            pathlib.Path(__file__).parent.parent.parent
            / "skills"
            / "skills"
            / "subscription-refund.yaml"
        )
        text = yaml_path.read_text()
        assert "stripe_refund_api" not in text, (
            "subscription-refund.yaml still references the non-existent "
            "`stripe_refund_api` tool. Use `stripe_api` (action=refund) — see #43."
        )
        assert "stripe_api" in text

    def test_refund_node_requires_approval(self):
        """Defense in depth: even with the high-stakes set, the YAML's
        negotiate node should carry requires_approval: true so the human
        gate fires regardless of memory-context heuristics."""
        import yaml

        yaml_path = (
            pathlib.Path(__file__).parent.parent.parent
            / "skills"
            / "skills"
            / "subscription-refund.yaml"
        )
        skill = yaml.safe_load(yaml_path.read_text())
        nodes = skill["execution_graph"]["nodes"]
        negotiate = next(n for n in nodes if n["id"] == "negotiate")
        assert negotiate.get("requires_approval") is True, (
            "negotiate node calls stripe_api refund and email_send — must "
            "carry requires_approval: true (SPEC §3b.8 Layer 3)"
        )
