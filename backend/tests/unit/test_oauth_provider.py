"""Unit tests for ComposioOAuthProvider (#57).

Pre-spike state: no OAuth provider existed.

Post-spike contract:
  - Disabled-by-default: every method raises OAuthProviderError when
    ENABLE_COMPOSIO is unset/false; no network calls.
  - Missing-key: enabled but no COMPOSIO_API_KEY → distinct error string.
  - Unknown-app rejection: only the apps PR A explicitly supports
    (gmail, google_calendar) pass; others raise.
  - Happy path: ``start`` returns an auth URL containing the app +
    redirect URI; ``complete`` returns the broker-shaped credential dict.
"""

from __future__ import annotations

import pytest

from backend.api.oauth.composio_provider import (
    COMPOSIO_OAUTH_DISABLED_ERROR,
    COMPOSIO_OAUTH_MISSING_CALLBACK_ID_ERROR,
    COMPOSIO_OAUTH_MISSING_KEY_ERROR,
    COMPOSIO_OAUTH_UNKNOWN_APP_ERROR,
    ComposioOAuthProvider,
)
from backend.api.oauth.provider import OAuthProviderError


@pytest.fixture(autouse=True)
def _no_composio_env(monkeypatch):
    monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)


@pytest.fixture
def provider():
    return ComposioOAuthProvider()


# ---------------------------------------------------------------------------
# is_enabled
# ---------------------------------------------------------------------------


def test_is_enabled_returns_false_by_default(provider):
    assert provider.is_enabled() is False


def test_is_enabled_true_when_flag_and_key_present(provider, monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
    assert provider.is_enabled() is True


def test_is_enabled_false_when_flag_only(provider, monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    assert provider.is_enabled() is False


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_raises_disabled_when_flag_off(provider):
    with pytest.raises(OAuthProviderError) as exc:
        await provider.start("gmail", redirect_uri="https://x/cb")
    assert str(exc.value) == COMPOSIO_OAUTH_DISABLED_ERROR


@pytest.mark.asyncio
async def test_start_raises_missing_key(provider, monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    with pytest.raises(OAuthProviderError) as exc:
        await provider.start("gmail", redirect_uri="https://x/cb")
    assert str(exc.value) == COMPOSIO_OAUTH_MISSING_KEY_ERROR


@pytest.mark.asyncio
async def test_start_rejects_unknown_app(provider, monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
    with pytest.raises(OAuthProviderError) as exc:
        await provider.start("salesforce", redirect_uri="https://x/cb")
    assert str(exc.value) == COMPOSIO_OAUTH_UNKNOWN_APP_ERROR


@pytest.mark.asyncio
async def test_start_returns_auth_url_and_state(provider, monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
    result = await provider.start("gmail", redirect_uri="https://x/cb")
    assert result.auth_url.startswith("https://backend.composio.dev/")
    assert "app=gmail" in result.auth_url
    assert "redirect_uri=https" in result.auth_url
    assert len(result.state) >= 16


@pytest.mark.asyncio
async def test_start_supports_google_calendar(provider, monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
    result = await provider.start("google_calendar", redirect_uri="https://x/cb")
    assert "app=google_calendar" in result.auth_url


# ---------------------------------------------------------------------------
# complete()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_raises_disabled_when_flag_off(provider):
    with pytest.raises(OAuthProviderError):
        await provider.complete("gmail", {"connected_account_id": "x"})


@pytest.mark.asyncio
async def test_complete_requires_connected_account_id(provider, monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
    with pytest.raises(OAuthProviderError) as exc:
        await provider.complete("gmail", {})
    assert str(exc.value) == COMPOSIO_OAUTH_MISSING_CALLBACK_ID_ERROR


@pytest.mark.asyncio
async def test_complete_returns_broker_shaped_creds(provider, monkeypatch):
    monkeypatch.setenv("ENABLE_COMPOSIO", "true")
    monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
    creds = await provider.complete(
        "gmail", {"connected_account_id": "ca_abc123"}
    )
    assert creds == {
        "connected_account_id": "ca_abc123",
        "broker": "composio",
        "app": "gmail",
    }
    # Critically: NO raw provider tokens (per ADR-0001)
    assert "access_token" not in creds
    assert "refresh_token" not in creds
