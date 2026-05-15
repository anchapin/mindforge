"""Tests for the OAuth refresh background worker (#57 part B).

Two-tier strategy mirroring the existing test_temporal.py:

  1. Activity-level tests: refresh_composio_bearers must be a clean
     structured no-op when ENABLE_COMPOSIO is off, and must enumerate
     only Composio-broker integration rows when on.
  2. Workflow definition tests: OAuthRefreshWorkflow must be properly
     decorated, registered in ALL_WORKFLOWS, and the schedule helper
     must be a no-op when TemporalClient is in stub mode.

End-to-end execution against a live Temporal broker stays out of scope
(same convention as test_temporal.py — covered by the docker-compose
"temporal" profile).
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet

# Pre-import patches -- same shape as test_oauth_routes.py
os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())

_original_makedirs = os.makedirs


def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)


os.makedirs = _patched_makedirs  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# DB scaffold
# ---------------------------------------------------------------------------

_INTEGRATION_DDL = """
CREATE TABLE IF NOT EXISTS integration (
    id                 TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    app_name           TEXT NOT NULL UNIQUE,
    auth_token_enc     TEXT NOT NULL,
    refresh_token_enc  TEXT,
    token_key_id       TEXT NOT NULL DEFAULT 'local',
    status             TEXT NOT NULL DEFAULT 'active',
    last_sync_at       TEXT,
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now')),
    extra              TEXT,
    permissions        TEXT NOT NULL DEFAULT '[]',
    allowed_agents     TEXT NOT NULL DEFAULT '[]'
);
"""


def _seed_integration(
    db_path: str,
    app_name: str,
    auth_blob: str,
    extra: str | None = None,
    last_sync_at: str | None = None,
) -> str:
    """Insert a fake integration row, return the new id."""
    import uuid

    row_id = str(uuid.uuid4())
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO integration (id, app_name, auth_token_enc, extra, last_sync_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (row_id, app_name, auth_blob, extra, last_sync_at),
    )
    conn.commit()
    conn.close()
    return row_id


def _read_last_sync(db_path: str, app_name: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT last_sync_at FROM integration WHERE app_name = ?",
            (app_name,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


@pytest.fixture
def db_path() -> Iterator[str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(_INTEGRATION_DDL)
    conn.commit()
    conn.close()
    try:
        yield tmp.name
    finally:
        os.unlink(tmp.name)


@pytest.fixture(autouse=True)
def _no_composio_env(monkeypatch):
    """Default: simulate a fresh install with no Composio config."""
    monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)


# ---------------------------------------------------------------------------
# 1. Activity-level behaviour
# ---------------------------------------------------------------------------


class TestRefreshActivityDisabled:
    """Triple-gated phase isolation -- when Composio is off, activity is a no-op."""

    @pytest.mark.asyncio
    async def test_returns_skipped_when_flag_off(self, db_path):
        from backend.scheduler.workflows.oauth_refresh import (
            OAuthRefreshParams,
            refresh_composio_bearers,
        )

        result = await refresh_composio_bearers(
            OAuthRefreshParams(db_path=db_path)
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "composio_disabled"
        assert result["refreshed"] == 0

    @pytest.mark.asyncio
    async def test_returns_skipped_when_key_missing(self, db_path, monkeypatch):
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        from backend.scheduler.workflows.oauth_refresh import (
            OAuthRefreshParams,
            refresh_composio_bearers,
        )

        result = await refresh_composio_bearers(
            OAuthRefreshParams(db_path=db_path)
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "composio_missing_key"
        assert result["refreshed"] == 0


class TestRefreshActivityEnumerates:
    """When enabled, the activity must enumerate only Composio rows and
    must NOT touch direct-API integrations (gmail-imap, github, etc.).

    The actual SDK call is intentionally a structured 'not_implemented'
    until #57 PR C wires the live Composio client; that's still a
    measurable behaviour we lock down here.
    """

    @pytest.mark.asyncio
    async def test_skips_non_composio_rows(self, db_path, monkeypatch):
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        # Phase 1 direct integrations -- no oauth_broker key
        _seed_integration(db_path, "github", auth_blob="ghp_x")
        _seed_integration(
            db_path, "stripe", auth_blob="sk_x", extra='{"oauth_broker":"none"}'
        )

        from backend.scheduler.workflows.oauth_refresh import (
            OAuthRefreshParams,
            refresh_composio_bearers,
        )

        result = await refresh_composio_bearers(
            OAuthRefreshParams(db_path=db_path)
        )
        # Nothing to refresh because no Composio rows exist
        assert result["status"] == "ok"
        assert result["refreshed"] == 0
        assert result["skipped_non_composio"] == 2

    @pytest.mark.asyncio
    async def test_attempts_refresh_on_composio_rows(self, db_path, monkeypatch):
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        # A Composio-mediated row that should be visited
        _seed_integration(
            db_path,
            "gmail",
            auth_blob="encrypted_blob",
            extra='{"oauth_broker":"composio"}',
        )

        from backend.scheduler.workflows.oauth_refresh import (
            REFRESH_NOT_IMPLEMENTED_REASON,
            OAuthRefreshParams,
            refresh_composio_bearers,
        )

        result = await refresh_composio_bearers(
            OAuthRefreshParams(db_path=db_path)
        )
        # Activity visited the row, attempted the refresh, and -- since the
        # live SDK is deferred -- recorded the structured not_implemented
        # outcome rather than crashing.
        assert result["status"] == "ok"
        assert result["attempted"] == 1
        assert result["refreshed"] == 0
        assert result["pending_implementation"] == 1
        # The per-row outcome is surfaced for ops visibility
        assert result["outcomes"][0]["app"] == "gmail"
        assert result["outcomes"][0]["reason"] == REFRESH_NOT_IMPLEMENTED_REASON

    @pytest.mark.asyncio
    async def test_updates_last_sync_at_for_visited_rows(
        self, db_path, monkeypatch
    ):
        """Even when the live SDK is stubbed, last_sync_at must advance so
        operators can see the worker is heartbeating against the row."""
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        _seed_integration(
            db_path,
            "gmail",
            auth_blob="encrypted_blob",
            extra='{"oauth_broker":"composio"}',
            last_sync_at=None,
        )
        assert _read_last_sync(db_path, "gmail") is None

        from backend.scheduler.workflows.oauth_refresh import (
            OAuthRefreshParams,
            refresh_composio_bearers,
        )

        await refresh_composio_bearers(OAuthRefreshParams(db_path=db_path))
        assert _read_last_sync(db_path, "gmail") is not None


# ---------------------------------------------------------------------------
# 2. Workflow / activity decoration + registry
# ---------------------------------------------------------------------------


class TestWorkflowRegistry:
    def test_workflow_registered(self):
        from backend.scheduler.workflows import (
            ALL_ACTIVITIES,
            ALL_WORKFLOWS,
            OAuthRefreshWorkflow,
            refresh_composio_bearers,
        )

        assert OAuthRefreshWorkflow in ALL_WORKFLOWS
        assert refresh_composio_bearers in ALL_ACTIVITIES

    def test_workflow_class_decorated(self):
        from temporalio.workflow import _Definition

        from backend.scheduler.workflows.oauth_refresh import OAuthRefreshWorkflow

        defn = _Definition.must_from_class(OAuthRefreshWorkflow)
        assert defn.name == "OAuthRefreshWorkflow"

    def test_activity_decorated(self):
        from temporalio.activity import _Definition

        from backend.scheduler.workflows.oauth_refresh import (
            refresh_composio_bearers,
        )

        defn = _Definition.must_from_callable(refresh_composio_bearers)
        assert defn.name == "refresh_composio_bearers"


# ---------------------------------------------------------------------------
# 3. Schedule helper -- must be a no-op in stub mode
# ---------------------------------------------------------------------------


class TestScheduleHelperStubMode:
    @pytest.mark.asyncio
    async def test_schedule_helper_noop_when_disabled(self, monkeypatch):
        monkeypatch.delenv("ENABLE_TEMPORAL", raising=False)
        from backend.scheduler.temporal_app import TemporalClient

        client = TemporalClient()
        # Helper attaches to the client; in stub mode it must NOT raise
        # and must NOT attempt any network call.
        from backend.scheduler.workflows.oauth_refresh import (
            ensure_oauth_refresh_schedule,
        )

        result = await ensure_oauth_refresh_schedule(client)
        assert result is False  # False == no schedule installed
