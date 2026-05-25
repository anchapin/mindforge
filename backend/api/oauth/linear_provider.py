"""Linear OAuth provider (#57, #153).

Implements the OAuthProvider protocol for Linear's OAuth 2.0 flow.
Linear docs: https://developers.linear.app/docs/oauth

The flow:
  1. /start -> redirect to Linear's authorization URL
  2. Linear redirects back with ?code=...
  3. /callback -> exchange code for access_token + refresh_token
  4. Store tokens Fernet-encrypted on the integration row

Linear OAuth Scopes
-------------------
offline_access  — required to get refresh_token (token rotation)
read            — read issues, projects, teams, etc.
write           — create/update issues, comments, etc.
"""

from __future__ import annotations

import os
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta

import httpx

from .provider import OAuthProviderError, OAuthStartResult

LINEAR_OAUTH_BASE = "https://linear.app/oauth"
LINEAR_API_URL = "https://api.linear.app/graphql"

_SCOPES = "offline_access read write"

_LINEAR_OAUTH_NOT_CONFIGURED_ERROR = (
    "linear_oauth_not_configured: LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET "
    "must be set to enable Linear OAuth. "
    "Set both environment variables and restart the server."
)
_LINEAR_OAUTH_MISSING_ID_ERROR = (
    "linear_oauth_missing_id: LINEAR_CLIENT_ID is not configured."
)
_LINEAR_OAUTH_MISSING_SECRET_ERROR = (
    "linear_oauth_missing_secret: LINEAR_CLIENT_SECRET is not configured."
)
_LINEAR_OAUTH_UNKNOWN_APP_ERROR = (
    "linear_oauth_unknown_app: provider does not support this app."
)
_LINEAR_OAUTH_MISSING_CODE_ERROR = (
    "linear_oauth_missing_code: Linear callback omitted the authorization code."
)
_LINEAR_OAUTH_TOKEN_ERROR = (
    "linear_oauth_token_failed: token exchange failed."
)

# Apps this provider handles directly (Linear only — others via Composio)
_SUPPORTED_APPS: frozenset[str] = frozenset({"linear"})


def _client_id() -> str | None:
    return os.getenv("LINEAR_CLIENT_ID", "").strip() or None


def _client_secret() -> str | None:
    return os.getenv("LINEAR_CLIENT_SECRET", "").strip() or None


def _redirect_uri() -> str:
    return os.getenv("LINEAR_OAUTH_REDIRECT_URI", "http://localhost:8000/api/oauth/linear/callback")


class LinearOAuthProvider:
    name = "linear"

    def is_enabled(self) -> bool:
        return _client_id() is not None and _client_secret() is not None

    async def start(self, app: str, redirect_uri: str) -> OAuthStartResult:
        if not self.is_enabled():
            raise OAuthProviderError(_LINEAR_OAUTH_NOT_CONFIGURED_ERROR)
        if _client_id() is None:
            raise OAuthProviderError(_LINEAR_OAUTH_MISSING_ID_ERROR)
        if _client_secret() is None:
            raise OAuthProviderError(_LINEAR_OAUTH_MISSING_SECRET_ERROR)
        if app not in _SUPPORTED_APPS:
            raise OAuthProviderError(_LINEAR_OAUTH_UNKNOWN_APP_ERROR)

        state_nonce = uuid.uuid4().hex
        params = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": _client_id(),
                "redirect_uri": redirect_uri,
                "scope": _SCOPES,
                "state": state_nonce,
            }
        )
        auth_url = f"{LINEAR_OAUTH_BASE}/authorize?{params}"
        return OAuthStartResult(auth_url=auth_url, state=state_nonce)

    async def complete(self, app: str, callback_params: dict[str, str]) -> dict[str, str]:
        if not self.is_enabled():
            raise OAuthProviderError(_LINEAR_OAUTH_NOT_CONFIGURED_ERROR)
        if _client_id() is None:
            raise OAuthProviderError(_LINEAR_OAUTH_MISSING_ID_ERROR)
        if _client_secret() is None:
            raise OAuthProviderError(_LINEAR_OAUTH_MISSING_SECRET_ERROR)
        if app not in _SUPPORTED_APPS:
            raise OAuthProviderError(_LINEAR_OAUTH_UNKNOWN_APP_ERROR)

        code = callback_params.get("code", "").strip()
        if not code:
            raise OAuthProviderError(_LINEAR_OAUTH_MISSING_CODE_ERROR)

        redirect_uri = _redirect_uri()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{LINEAR_OAUTH_BASE}/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": _client_id(),
                    "client_secret": _client_secret(),
                },
            )
            if resp.status_code != 200:
                raise OAuthProviderError(_LINEAR_OAUTH_TOKEN_ERROR)

            token_data = resp.json()
            access_token = token_data.get("access_token", "")
            refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 0)

            expires_at = (
                datetime.now(UTC) + timedelta(seconds=expires_in)
                if expires_in
                else None
            )

        return {
            "access_token": access_token,
            "refresh_token": refresh_token or "",
            "token_type": token_data.get("token_type", "Bearer"),
            "expires_at": expires_at.isoformat() if expires_at else "",
            "broker": "linear",
            "app": app,
        }


LINEAR_PROVIDER = LinearOAuthProvider()
