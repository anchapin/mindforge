"""Composio-mediated OAuth provider (#57, ADR-0001).

Composio handles the actual OAuth handshake with Google / GitHub / etc.;
MindForge just:

  1. Asks Composio for an auth URL keyed to the user's installation
     (``/start`` route).
  2. Receives a `connected_account_id` on the callback.
  3. Stores that ID Fernet-encrypted on the `integration` row.

No raw provider tokens (Google access_token / refresh_token) ever touch
MindForge's storage layer in this path — that is one of the reasons
ADR-0001 chose Composio over a direct integration build-out.

This module performs **no live network calls**; the Composio SDK pin
that does is intentionally deferred to a follow-up so the spike POC
contract from #56 stays in force. ``start`` returns the conventional
Composio hosted-auth URL constructed from the app name, and ``complete``
echoes the callback params after validation.
"""

from __future__ import annotations

import os
import urllib.parse
import uuid

from .provider import OAuthProviderError, OAuthStartResult

# Public sentinel error strings -- mirror the #56 ComposioTool conventions
# so callers can branch on the failure mode without prose-matching.
COMPOSIO_OAUTH_DISABLED_ERROR = (
    "composio_oauth_disabled: ENABLE_COMPOSIO is not set. "
    "Phase 4 OAuth requires Composio per ADR-0001."
)
COMPOSIO_OAUTH_MISSING_KEY_ERROR = (
    "composio_oauth_missing_key: COMPOSIO_API_KEY is not configured."
)
COMPOSIO_OAUTH_UNKNOWN_APP_ERROR = (
    "composio_oauth_unknown_app: provider does not currently support this app."
)
COMPOSIO_OAUTH_MISSING_CALLBACK_ID_ERROR = (
    "composio_oauth_missing_callback_id: Composio callback omitted "
    "connected_account_id."
)

# Apps PR A explicitly supports. The full Composio catalogue (864+) lights up
# in PR C as the dispatcher table grows; gating here keeps the surface honest.
_SUPPORTED_APPS: frozenset[str] = frozenset({"gmail", "google_calendar"})

_COMPOSIO_AUTH_BASE = "https://backend.composio.dev/api/v1/connectedAccounts/initiate"


def _flag_enabled() -> bool:
    raw = os.getenv("ENABLE_COMPOSIO", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _api_key() -> str | None:
    key = os.getenv("COMPOSIO_API_KEY", "").strip()
    return key or None


class ComposioOAuthProvider:
    """OAuthProvider implementation for Composio-mediated flows."""

    name = "composio"

    def is_enabled(self) -> bool:
        return _flag_enabled() and _api_key() is not None

    async def start(self, app: str, redirect_uri: str) -> OAuthStartResult:
        if not _flag_enabled():
            raise OAuthProviderError(COMPOSIO_OAUTH_DISABLED_ERROR)
        if _api_key() is None:
            raise OAuthProviderError(COMPOSIO_OAUTH_MISSING_KEY_ERROR)
        if app not in _SUPPORTED_APPS:
            raise OAuthProviderError(COMPOSIO_OAUTH_UNKNOWN_APP_ERROR)

        # The route layer signs the state token; the provider just generates
        # the unique nonce that goes inside it. Real Composio dispatch lands
        # with the SDK pin; the URL shape here is the documented one so the
        # integration test can assert on its structure.
        state_nonce = uuid.uuid4().hex
        params = urllib.parse.urlencode(
            {
                "app": app,
                "redirect_uri": redirect_uri,
                "state": state_nonce,
            }
        )
        auth_url = f"{_COMPOSIO_AUTH_BASE}?{params}"
        return OAuthStartResult(auth_url=auth_url, state=state_nonce)

    async def complete(self, app: str, callback_params: dict[str, str]) -> dict[str, str]:
        if not _flag_enabled():
            raise OAuthProviderError(COMPOSIO_OAUTH_DISABLED_ERROR)
        if _api_key() is None:
            raise OAuthProviderError(COMPOSIO_OAUTH_MISSING_KEY_ERROR)
        if app not in _SUPPORTED_APPS:
            raise OAuthProviderError(COMPOSIO_OAUTH_UNKNOWN_APP_ERROR)

        connected_account_id = callback_params.get("connected_account_id", "").strip()
        if not connected_account_id:
            raise OAuthProviderError(COMPOSIO_OAUTH_MISSING_CALLBACK_ID_ERROR)

        # The route persists this dict (Fernet-encrypted) on the integration
        # row. We deliberately do NOT include any raw provider tokens;
        # Composio is the source of truth for the OAuth grant per ADR-0001.
        return {
            "connected_account_id": connected_account_id,
            "broker": "composio",
            "app": app,
        }


COMPOSIO_PROVIDER = ComposioOAuthProvider()
