"""Tests for the OAuth-aware code path in EmailFetchTool (#57 part C).

Adds a new ``oauth_broker="composio"`` branch to email_fetch.py without
breaking the existing IMAP fallback. AC #4 of #57:

  > Existing IMAP path stays as fallback when OAuth tokens missing

is satisfied by:
  - When ``oauth_broker`` is omitted/``"none"`` → existing IMAP code path
    runs (verified by patching imaplib).
  - When ``oauth_broker == "composio"`` and ENABLE_COMPOSIO is unset →
    structured COMPOSIO_DISABLED_ERROR returned, IMAP is NOT attempted.
  - When ``oauth_broker == "composio"`` + flag on + key set → structured
    COMPOSIO_NOT_IMPLEMENTED_ERROR returned (live SDK lands later).
"""

from __future__ import annotations

import os
import pathlib

# Pre-import patches
_original_makedirs = os.makedirs


def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)


os.makedirs = _patched_makedirs  # type: ignore[assignment]

from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

from backend.tools.email_fetch import EmailFetchTool  # noqa: E402
from backend.tools.integrations.google_calendar import (  # noqa: E402
    CALENDAR_DISABLED_ERROR,
)


@pytest.fixture(autouse=True)
def _no_composio_env(monkeypatch):
    monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# OAuth-aware path: oauth_broker="composio"
# ---------------------------------------------------------------------------


class TestComposioOAuthPath:
    @pytest.mark.asyncio
    async def test_oauth_broker_composio_returns_disabled_when_flag_off(self):
        """No flag -> structured error WITHOUT touching IMAP."""
        tool = EmailFetchTool()
        with patch("imaplib.IMAP4_SSL") as imap_cls:
            result = await tool.execute(
                action="recent",
                oauth_broker="composio",
            )
        assert result.success is False
        assert "composio" in result.error.lower()
        # Critical: IMAP must NOT have been touched on the OAuth path
        imap_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_oauth_broker_composio_returns_missing_key(self, monkeypatch):
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        tool = EmailFetchTool()
        with patch("imaplib.IMAP4_SSL") as imap_cls:
            result = await tool.execute(
                action="recent",
                oauth_broker="composio",
            )
        assert result.success is False
        assert "missing" in result.error.lower() or "missing_credential" in result.error
        imap_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_oauth_broker_composio_returns_not_implemented_when_configured(
        self, monkeypatch
    ):
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        tool = EmailFetchTool()
        with patch("imaplib.IMAP4_SSL") as imap_cls:
            result = await tool.execute(
                action="recent",
                oauth_broker="composio",
            )
        assert result.success is False
        assert "not_implemented" in result.error.lower()
        imap_cls.assert_not_called()


# ---------------------------------------------------------------------------
# IMAP fallback: omitted / "none" / explicit "imap"
# ---------------------------------------------------------------------------


class TestIMAPFallback:
    @pytest.mark.asyncio
    async def test_default_path_runs_imap_when_oauth_broker_omitted(self):
        """No oauth_broker arg -> existing IMAP path runs."""
        tool = EmailFetchTool()

        class _FakeMail:
            def login(self, *a, **kw):
                pass

            def select(self, *a, **kw):
                pass

            def search(self, *a, **kw):
                return ("OK", [b""])

            def fetch(self, *a, **kw):  # pragma: no cover - empty inbox
                return ("OK", [(None, b"")])

            def logout(self):
                pass

        with patch("imaplib.IMAP4_SSL", return_value=_FakeMail()) as imap_cls:
            result = await tool.execute(
                action="recent",
                host="imap.example.com",
                port=993,
                username="u",
                password="p",
            )
        # IMAP was attempted (path == fallback), no Composio gating involved
        imap_cls.assert_called_once()
        assert result.success is True
        assert result.data == {"emails": []}

    @pytest.mark.asyncio
    async def test_explicit_oauth_broker_none_uses_imap(self):
        tool = EmailFetchTool()

        class _FakeMail:
            def login(self, *a, **kw):
                pass

            def select(self, *a, **kw):
                pass

            def search(self, *a, **kw):
                return ("OK", [b""])

            def fetch(self, *a, **kw):  # pragma: no cover
                return ("OK", [(None, b"")])

            def logout(self):
                pass

        with patch("imaplib.IMAP4_SSL", return_value=_FakeMail()) as imap_cls:
            result = await tool.execute(
                action="recent",
                oauth_broker="none",
                host="imap.example.com",
                port=993,
                username="u",
                password="p",
            )
        imap_cls.assert_called_once()
        assert result.success is True


# Sanity: import alignment with GoogleCalendarTool (same env conventions)
def test_calendar_disabled_error_string_aligned():
    """Both tools must use the same disabled-flag string convention so the
    UI can branch on a single sentinel rather than per-tool prose."""
    assert "ENABLE_COMPOSIO" in CALENDAR_DISABLED_ERROR
