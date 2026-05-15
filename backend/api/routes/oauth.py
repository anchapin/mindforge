"""OAuth routes -- /api/oauth/{provider}/start and /callback (#57).

Per ADR-0001 the only registered provider is ``composio``; the route
layer is provider-agnostic so a future direct-OAuth path can plug in
without breaking callers.

State-token CSRF defence
------------------------
``/start`` returns a Fernet-encrypted state token containing the app
name + nonce + a short TTL. ``/callback`` validates the token before
completing the grant. This piggybacks on the existing ``FERNET_KEY``
env var (SPEC §3b.5) -- no new secret to manage.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..deps import db_dep
from ..oauth import (
    COMPOSIO_PROVIDER,
    OAuthProviderError,
    get_provider,
    register_provider,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/oauth", tags=["oauth"])

# Register the only provider that ships in PR A. PR B/C will not add new
# providers -- they extend Composio coverage instead.
register_provider(COMPOSIO_PROVIDER)

_STATE_TTL_SECONDS = 600  # 10 minutes -- generous for slow OAuth dialogs

FERNET_KEY = os.getenv("FERNET_KEY", "")
_fernet: Fernet | None = Fernet(FERNET_KEY.encode()) if FERNET_KEY else None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sign_state(payload: dict) -> str:
    """Encode + Fernet-encrypt the state token. Falls back to plain JSON
    only when no FERNET_KEY is set (test/dev convenience -- production
    must always set FERNET_KEY)."""
    blob = json.dumps(payload, separators=(",", ":")).encode()
    if _fernet is None:
        return blob.decode()
    return _fernet.encrypt(blob).decode()


def _verify_state(state: str) -> dict:
    """Decrypt + decode + TTL-check. Raises HTTPException(400) on any
    failure mode so callers see a uniform CSRF-style rejection."""
    try:
        if _fernet is None:
            payload = json.loads(state)
        else:
            payload = json.loads(_fernet.decrypt(state.encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid_state") from exc

    issued = payload.get("iat", 0)
    if not isinstance(issued, (int, float)) or issued <= 0:
        raise HTTPException(status_code=400, detail="invalid_state")
    if time.time() - issued > _STATE_TTL_SECONDS:
        raise HTTPException(status_code=400, detail="expired_state")
    return payload


def _encrypt_blob(blob: str) -> str:
    return _fernet.encrypt(blob.encode()).decode() if _fernet else blob


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class OAuthStartRequest(BaseModel):
    app: str = Field(..., min_length=1, max_length=64)


class OAuthStartResponse(BaseModel):
    auth_url: str
    state: str


class OAuthCallbackResponse(BaseModel):
    integration_id: str
    app_name: str
    broker: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/{provider}/start", response_model=OAuthStartResponse)
async def oauth_start(
    provider: str, payload: OAuthStartRequest, request: Request
) -> OAuthStartResponse:
    """Begin an OAuth grant. Returns the auth URL + signed state token."""
    impl = get_provider(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"unknown_provider:{provider}")

    redirect_uri = str(request.url_for("oauth_callback", provider=provider))
    try:
        result = await impl.start(payload.app, redirect_uri=redirect_uri)
    except OAuthProviderError as exc:
        # 503 = provider not ready; the dashboard surfaces the message.
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    state_token = _sign_state(
        {
            "provider": provider,
            "app": payload.app,
            "nonce": result.state,
            "iat": int(time.time()),
        }
    )
    logger.info("oauth_start provider=%s app=%s", provider, payload.app)
    return OAuthStartResponse(auth_url=result.auth_url, state=state_token)


@router.get("/{provider}/callback", response_model=OAuthCallbackResponse, name="oauth_callback")
async def oauth_callback(
    provider: str,
    state: str,
    request: Request,
    db: sqlite3.Connection = Depends(db_dep),
) -> OAuthCallbackResponse:
    """Finalise the grant: persist Fernet-encrypted credentials, return id."""
    impl = get_provider(provider)
    if impl is None:
        raise HTTPException(status_code=404, detail=f"unknown_provider:{provider}")

    payload = _verify_state(state)
    if payload.get("provider") != provider:
        raise HTTPException(status_code=400, detail="state_provider_mismatch")
    app = payload.get("app", "")
    if not app:
        raise HTTPException(status_code=400, detail="state_missing_app")

    # Pass through any extra query params -- Composio sends
    # `connected_account_id`; future providers may send `code` etc.
    extras = {k: v for k, v in request.query_params.items() if k != "state"}
    try:
        creds = await impl.complete(app, extras)
    except OAuthProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    encrypted = _encrypt_blob(json.dumps(creds, separators=(",", ":")))
    integration_id = str(uuid.uuid4())
    now = _now_iso()
    try:
        db.execute(
            "INSERT INTO integration "
            "(id, app_name, auth_token_enc, status, created_at, updated_at, extra) "
            "VALUES (?, ?, ?, 'active', ?, ?, ?)",
            (integration_id, app, encrypted, now, now, json.dumps({"oauth_broker": creds.get("broker", provider)})),
        )
        db.commit()
    except sqlite3.IntegrityError:
        # An existing integration row for this app -- update in place so
        # re-authorising Gmail/Calendar refreshes the stored credentials.
        db.execute(
            "UPDATE integration SET auth_token_enc = ?, status = 'active', "
            "updated_at = ?, extra = ? WHERE app_name = ?",
            (encrypted, now, json.dumps({"oauth_broker": creds.get("broker", provider)}), app),
        )
        db.commit()
        existing = db.execute(
            "SELECT id FROM integration WHERE app_name = ?", (app,)
        ).fetchone()
        integration_id = existing["id"] if existing else integration_id

    logger.info("oauth_callback_persisted provider=%s app=%s", provider, app)
    return OAuthCallbackResponse(
        integration_id=integration_id, app_name=app, broker=creds.get("broker", provider)
    )
