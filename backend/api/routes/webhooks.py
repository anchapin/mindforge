"""Stripe webhook handler — Task 13.

POST /webhooks/stripe with HMAC-SHA256 signature validation.
Billing anomaly (amount > threshold) triggers draft-first workflow.
Webhook processing logged to episodic memory.

Signature validation:
  Stripe-Signature header format: t=timestamp,v1=signature
  We compute HMAC-SHA256(secret, timestamp + "." + payload) and compare.

Billing anomaly detection:
  If invoice.paid amount > billing_alert_threshold_usd (default $100) → draft task.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from ...memory.episodic import EpisodicMemory
from ...memory.store import SharedMemoryStore
from ..deps import get_ws_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

BILLING_ALERT_THRESHOLD_USD = float(os.getenv("BILLING_ALERT_THRESHOLD_USD", "100"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_stripe_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    """Validate Stripe HMAC-SHA256 webhook signature.

    Stripe signature header format: "t=timestamp,v1=signature"
    We compute: HMAC-SHA256(secret, timestamp + "." + payload)
    and compare against the provided v1 signature using timing-safe comparison.
    """
    if not signature_header:
        return False

    try:
        # Parse t=timestamp,v1=signature
        parts = dict(p.split("=", 1) for p in signature_header.split(","))
        timestamp = parts.get("t", "")
        received_sig = parts.get("v1", "")

        if not timestamp or not received_sig:
            return False

        # Compute expected signature: HMAC-SHA256(secret, timestamp + "." + payload)
        signed_payload = f"{timestamp}.".encode() + payload
        expected_sig = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()

        return hmac.compare_digest(expected_sig, received_sig)
    except Exception:
        return False


def _get_task_db():
    """Get task DB connection. Lazily imported to avoid circular deps."""
    from ..deps import get_db as _get_db
    return _get_db()


async def _log_to_episodic(event_type: str, payload: dict, source: str = "stripe") -> None:
    """Log a webhook event to episodic memory (async)."""
    try:
        store = SharedMemoryStore()
        await store.start()
        record_id = f"ep_{int(time.time() * 1000)}"
        now = datetime.now(UTC)
        record = EpisodicMemory(
            id=record_id,
            project_id=None,
            task_id=f"stripe_{event_type}",
            task_type="finance",
            agent_role="system",
            summary=f"Stripe webhook: {event_type}",
            outcome_status="completed",
            feedback=json.dumps(payload),
            created_at=now,
        )
        await store._episodic.insert(record)
        logger.debug("Logged stripe webhook to episodic: %s", event_type)
    except Exception as exc:
        logger.warning("Failed to log stripe webhook to episodic memory: %s", exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


async def stripe_webhook(request: Request) -> dict:
    """POST /webhooks/stripe — handle Stripe webhook events.

    1. Validate HMAC-SHA256 signature (fast, within 3s SLA)
    2. Parse event type
    3. Log to episodic memory (sync, non-blocking)
    4. If billing anomaly (invoice.paid > threshold) → draft task for approval

    Returns: {"received": True} or {"received": True, "anomaly_detected": True}
    """
    webhook_secret = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    # Always read body first (Stripe requires this for signature validation)
    payload = await request.body()

    # Validate signature
    sig_header = request.headers.get("stripe-signature", "")
    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET not configured — rejecting webhook")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    if not _validate_stripe_signature(payload, sig_header, webhook_secret):
        logger.warning("Stripe webhook signature validation failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Parse event
    try:
        event = json.loads(payload.decode())
    except json.JSONDecodeError:
        logger.warning("Stripe webhook payload is not valid JSON")
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_id = event.get("id", "")
    event_type = event.get("type", "")

    logger.info("Stripe webhook received: event_id=%s type=%s", event_id, event_type)

    # Always log to episodic memory (async)
    await _log_to_episodic(
        event_type=f"stripe_webhook:{event_type}",
        payload=event,
        source="stripe",
    )

    # Check for billing anomaly
    anomaly_detected = False

    if event_type == "invoice.paid":
        amount_paid = (event.get("data", {}) or {}).get("object", {}).get("amount_paid", 0)
        threshold_cents = int(BILLING_ALERT_THRESHOLD_USD * 100)

        if amount_paid > threshold_cents:
            anomaly_detected = True
            logger.warning(
                "Billing anomaly detected: invoice amount %s cents > threshold %s cents",
                amount_paid,
                threshold_cents,
            )
            await _create_billing_draft_task(event, amount_paid)

    return {"received": True, "anomaly_detected": anomaly_detected}


async def _create_billing_draft_task(event: dict, amount_cents: int) -> None:
    """Create a draft task for user approval when billing anomaly is detected.

    Uses the draft-first workflow: task created in draft state, user approves.
    """
    try:
        db = _get_task_db()
        ws = get_ws_manager()

        customer_id = (event.get("data", {}) or {}).get("object", {}).get("customer", "unknown")
        invoice_id = (event.get("data", {}) or {}).get("object", {}).get("id", "unknown")
        amount_dollars = amount_cents / 100.0

        task_id = f"billing_anomaly_{int(time.time())}"
        now = datetime.now(UTC).isoformat()
        draft_payload = {
            "event": event,
            "amount_dollars": amount_dollars,
            "customer_id": customer_id,
            "invoice_id": invoice_id,
        }

        db.execute(
            """
            INSERT INTO tasks (id, description, status, created_at, updated_at, draft_output)
            VALUES (?, ?, 'draft', ?, ?, ?)
            """,
            (
                task_id,
                f"Billing anomaly: Stripe invoice {invoice_id} for ${amount_dollars:.2f} from customer {customer_id}. Please review and approve.",
                now,
                now,
                json.dumps(draft_payload),
            ),
        )
        db.commit()

        # Notify via WebSocket — draft ready for approval
        if ws:
            await ws.send_draft_ready(
                task_id=task_id,
                node_id="billing_anomaly",
                draft=draft_payload,
                approval_deadline_iso=datetime.now(UTC).isoformat(),
            )

        logger.info("Created billing anomaly draft task: %s", task_id)

    except Exception as exc:
        logger.error("Failed to create billing anomaly draft task: %s", exc)
