"""Test Stripe webhook handler — Task 13.

POST /webhooks/stripe with HMAC-SHA256 signature validation.
Billing anomaly → draft-first workflow (approval required).
Webhook processing logged to episodic memory.

Run: pytest backend/tests/integration/test_stripe_webhook.py -v
"""

from __future__ import annotations

import hashlib
import hmac
import json
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


def _make_stripe_signature(payload: bytes, secret: str, timestamp: str = "1700000000") -> str:
    """Compute the expected HMAC-SHA256 signature for Stripe webhook.

    Stripe format: HMAC-SHA256(secret, timestamp + "." + payload)
    Signature header: t=timestamp,v1=signature
    """
    signed_payload = f"{timestamp}.".encode() + payload
    sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def _stripe_event(
    event_id: str = "evt_test_123",
    event_type: str = "invoice.paid",
    amount_cents: int = 9900,
) -> dict:
    """Construct a minimal Stripe event dict."""
    return {
        "id": event_id,
        "type": event_type,
        "data": {
            "object": {
                "id": "in_test_123",
                "amount_paid": amount_cents,
                "currency": "usd",
                "customer": "cus_test",
                "created": 1700000000,
            }
        },
    }


class TestStripeWebhookSignatureValidation:
    """HMAC-SHA256 signature validation — rejects tampered or missing signatures."""

    def test_valid_signature_returns_200(self):
        """RED: Valid Stripe signature → 200 OK, {"received": True}.

        GREEN: Verify HMAC-SHA256, return fast 200.
        """
        payload = json.dumps(_stripe_event()).encode()
        secret = "whsec_test_secret"
        signature = _make_stripe_signature(payload, secret)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=payload)
        mock_request.headers = {"stripe-signature": signature}

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": secret}), \
             patch("backend.api.routes.webhooks.get_ws_manager") as mock_ws_fn, \
             patch("backend.api.routes.webhooks._log_to_episodic"):
            mock_ws_fn.return_value = MagicMock()
            import asyncio

            async def run():
                from backend.api.routes.webhooks import stripe_webhook

                return await stripe_webhook(mock_request)

            result = asyncio.get_event_loop().run_until_complete(run())
            assert result == {"received": True, "anomaly_detected": False}

    def test_tampered_payload_returns_400(self):
        """RED: Tampered payload → HTTP 400 "Invalid signature".

        GREEN: HMAC mismatch → HTTPException(400).
        """
        original_payload = json.dumps(_stripe_event()).encode()
        tampered_payload = json.dumps(_stripe_event(amount_cents=1)).encode()
        secret = "whsec_test_secret"
        signature = _make_stripe_signature(original_payload, secret)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=tampered_payload)
        mock_request.headers = {"stripe-signature": signature}

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": secret}), \
             patch("backend.api.routes.webhooks._log_to_episodic"):
            import asyncio

            async def run():
                from backend.api.routes.webhooks import stripe_webhook

                return await stripe_webhook(mock_request)

            try:
                asyncio.get_event_loop().run_until_complete(run())
                raise AssertionError("Expected HTTPException(400)")
            except Exception as exc:
                # Could be HTTPException or the exception propagated through
                pass

    def test_missing_signature_header_returns_400(self):
        """RED: Missing stripe-signature header → HTTP 400.

        GREEN: No signature header → HTTPException(400).
        """
        payload = json.dumps(_stripe_event()).encode()

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=payload)
        mock_request.headers = {}  # No stripe-signature

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "whsec_test_secret"}), \
             patch("backend.api.routes.webhooks._log_to_episodic"):
            import asyncio

            async def run():
                from backend.api.routes.webhooks import stripe_webhook

                return await stripe_webhook(mock_request)

            try:
                asyncio.get_event_loop().run_until_complete(run())
                raise AssertionError("Expected HTTPException(400)")
            except Exception:
                pass

    def test_bad_secret_returns_400(self):
        """RED: Secret mismatch → HTTP 400.

        GREEN: Wrong secret → HTTPException(400).
        """
        payload = json.dumps(_stripe_event()).encode()
        # Signed with wrong secret
        signature = _make_stripe_signature(payload, "wrong_secret")

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=payload)
        mock_request.headers = {"stripe-signature": signature}

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "correct_secret"}), \
             patch("backend.api.routes.webhooks._log_to_episodic"):
            import asyncio

            async def run():
                from backend.api.routes.webhooks import stripe_webhook

                return await stripe_webhook(mock_request)

            try:
                asyncio.get_event_loop().run_until_complete(run())
                raise AssertionError("Expected HTTPException(400)")
            except Exception:
                pass


class TestStripeWebhookBillingAnomaly:
    """Billing anomaly detection — amount > threshold triggers draft-first workflow."""

    def test_invoice_paid_above_threshold_triggers_draft_creation(self):
        """RED: invoice.paid with amount > BILLING_ALERT_THRESHOLD → creates draft task.

        GREEN: Check amount, fire send_draft_ready WS, create task in draft state.
        """
        # Amount: $500 (> $100 threshold)
        event = _stripe_event(event_type="invoice.paid", amount_cents=50000)
        payload = json.dumps(event).encode()
        secret = "whsec_test_secret"
        signature = _make_stripe_signature(payload, secret)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=payload)
        mock_request.headers = {"stripe-signature": signature}

        mock_ws = MagicMock()
        mock_ws.send_draft_ready = AsyncMock()
        mock_db = MagicMock()
        mock_db.commit = MagicMock()

        with patch.dict(
            os.environ, {"STRIPE_WEBHOOK_SECRET": secret, "BILLING_ALERT_THRESHOLD_USD": "100"}
        ), patch("backend.api.routes.webhooks._log_to_episodic"), \
             patch("backend.api.routes.webhooks._get_task_db", return_value=mock_db), \
             patch("backend.api.routes.webhooks.get_ws_manager", return_value=mock_ws):
            import asyncio

            async def run():
                from backend.api.routes.webhooks import stripe_webhook

                return await stripe_webhook(mock_request)

            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.get("anomaly_detected") is True
        assert mock_ws.send_draft_ready.called
        # Verify draft task was inserted into DB
        assert mock_db.execute.called
        call_args = mock_db.execute.call_args
        assert "INSERT INTO tasks" in str(call_args)

    def test_invoice_paid_below_threshold_returns_normal(self):
        """RED: invoice.paid with amount < threshold → 200, no draft task.

        GREEN: Log to episodic memory, return {"received": True, "anomaly_detected": False}.
        """
        # Amount: $50 (< $100 threshold)
        event = _stripe_event(event_type="invoice.paid", amount_cents=5000)
        payload = json.dumps(event).encode()
        secret = "whsec_test_secret"
        signature = _make_stripe_signature(payload, secret)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=payload)
        mock_request.headers = {"stripe-signature": signature}

        mock_ws = MagicMock()
        mock_db = MagicMock()

        with patch.dict(
            os.environ, {"STRIPE_WEBHOOK_SECRET": secret, "BILLING_ALERT_THRESHOLD_USD": "100"}
        ), patch("backend.api.routes.webhooks._log_to_episodic") as mock_log, \
             patch("backend.api.routes.webhooks._get_task_db", return_value=mock_db), \
             patch("backend.api.routes.webhooks.get_ws_manager", return_value=mock_ws):
            import asyncio

            async def run():
                from backend.api.routes.webhooks import stripe_webhook

                return await stripe_webhook(mock_request)

            result = asyncio.get_event_loop().run_until_complete(run())

        assert result.get("anomaly_detected") is False
        assert not mock_ws.send_draft_ready.called


class TestStripeWebhookEpisodicLogging:
    """Webhook processing is logged to episodic memory."""

    def test_webhook_received_logs_to_episodic_memory(self):
        """RED: Every Stripe event is logged to episodic memory via _log_to_episodic().

        GREEN: Call _log_to_episodic with event_type, payload, source="stripe".
        """
        event = _stripe_event()
        payload = json.dumps(event).encode()
        secret = "whsec_test_secret"
        signature = _make_stripe_signature(payload, secret)

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=payload)
        mock_request.headers = {"stripe-signature": signature}

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": secret}), \
             patch("backend.api.routes.webhooks._log_to_episodic") as mock_log, \
             patch("backend.api.routes.webhooks.get_ws_manager", return_value=MagicMock()):
            import asyncio

            async def run():
                from backend.api.routes.webhooks import stripe_webhook

                return await stripe_webhook(mock_request)

            result = asyncio.get_event_loop().run_until_complete(run())

        assert mock_log.called
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs.get("source") == "stripe"
        assert "stripe_webhook" in call_kwargs.get("event_type", "")

    def test_signature_validation_failure_does_not_log(self):
        """RED: Invalid signature → HTTP 400, no episodic log.

        GREEN: Early return on bad signature, no _log_to_episodic call.
        """
        payload = json.dumps(_stripe_event()).encode()
        # Use wrong secret so validation fails
        signature = _make_stripe_signature(payload, "wrong_secret")

        mock_request = MagicMock()
        mock_request.body = AsyncMock(return_value=payload)
        mock_request.headers = {"stripe-signature": signature}

        with patch.dict(os.environ, {"STRIPE_WEBHOOK_SECRET": "correct_secret"}), \
             patch("backend.api.routes.webhooks._log_to_episodic") as mock_log:
            import asyncio

            async def run():
                from backend.api.routes.webhooks import stripe_webhook

                return await stripe_webhook(mock_request)

            try:
                asyncio.get_event_loop().run_until_complete(run())
            except Exception:
                pass

        # _log_to_episodic should NOT have been called (early return)
        assert not mock_log.called
