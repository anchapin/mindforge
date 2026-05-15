"""End-to-end tests for /api/oauth/{provider}/* (#57).

Exercises the full route → provider → DB persist round-trip with
TestClient + an isolated SQLite DB. Verifies:

  - /start with the flag off returns a clean 503, NOT a 500
  - /start with the flag on issues an auth URL and a Fernet-signed state
  - /callback validates the state token (CSRF defence) and persists the
    Composio connected_account_id Fernet-encrypted on the integration row
  - Phase isolation: when ENABLE_COMPOSIO is unset, no integration row
    is ever created
"""

from __future__ import annotations

# ----- pre-import patches --------------------------------------------------
import os
import pathlib
import tempfile

from cryptography.fernet import Fernet

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())

_ORIGINAL_MAKEDIRS = os.makedirs


def _safe_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _ORIGINAL_MAKEDIRS(path, *args, **kwargs)


os.makedirs = _safe_makedirs  # type: ignore[assignment]
# ----------------------------------------------------------------------------

import json  # noqa: E402
import sqlite3  # noqa: E402
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

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


def _init_test_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(_INTEGRATION_DDL)
    conn.commit()
    conn.close()


@pytest.fixture
def db_path() -> Iterator[str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115
    tmp.close()
    _init_test_db(tmp.name)
    try:
        yield tmp.name
    finally:
        os.unlink(tmp.name)


@pytest.fixture
def client(db_path: str) -> Iterator[TestClient]:
    from backend.api.deps import db_dep
    from backend.api.routes import oauth

    app = FastAPI()
    app.include_router(oauth.router)

    def _override_db_dep() -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[db_dep] = _override_db_dep
    with TestClient(app) as c:
        yield c


def _read_integration(db_path: str, app: str) -> dict | None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, app_name, auth_token_enc, status, extra "
            "FROM integration WHERE app_name = ?",
            (app,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Phase isolation
# ---------------------------------------------------------------------------


class TestPhaseIsolation:
    """ENABLE_COMPOSIO unset must keep Phase 1-3 byte-identical."""

    def test_start_returns_503_when_flag_off(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
        resp = client.post("/api/oauth/composio/start", json={"app": "gmail"})
        assert resp.status_code == 503
        assert "ENABLE_COMPOSIO" in resp.json()["detail"]

    def test_no_integration_row_created_when_flag_off(
        self, client: TestClient, db_path: str, monkeypatch
    ) -> None:
        monkeypatch.delenv("ENABLE_COMPOSIO", raising=False)
        client.post("/api/oauth/composio/start", json={"app": "gmail"})
        assert _read_integration(db_path, "gmail") is None


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------


class TestOAuthStart:
    def test_unknown_provider_404(self, client: TestClient) -> None:
        resp = client.post("/api/oauth/whatever/start", json={"app": "gmail"})
        assert resp.status_code == 404

    def test_start_returns_auth_url_and_state(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        resp = client.post(
            "/api/oauth/composio/start", json={"app": "gmail"}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["auth_url"].startswith("https://backend.composio.dev/")
        assert "app=gmail" in body["auth_url"]
        # state must be opaque/long enough to defeat trivial guessing
        assert len(body["state"]) > 32

    def test_start_rejects_missing_key(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
        resp = client.post(
            "/api/oauth/composio/start", json={"app": "gmail"}
        )
        assert resp.status_code == 503
        assert "COMPOSIO_API_KEY" in resp.json()["detail"]

    def test_start_rejects_unknown_app(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        resp = client.post(
            "/api/oauth/composio/start", json={"app": "salesforce"}
        )
        assert resp.status_code == 503  # provider rejection
        assert "unknown_app" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# /callback round-trip
# ---------------------------------------------------------------------------


class TestOAuthCallback:
    def _start_and_get_state(self, client: TestClient) -> str:
        resp = client.post(
            "/api/oauth/composio/start", json={"app": "gmail"}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["state"]

    def test_callback_persists_encrypted_creds(
        self, client: TestClient, db_path: str, monkeypatch
    ) -> None:
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        state = self._start_and_get_state(client)

        resp = client.get(
            "/api/oauth/composio/callback",
            params={"state": state, "connected_account_id": "ca_abc123"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["app_name"] == "gmail"
        assert body["broker"] == "composio"
        assert body["integration_id"]

        # Persisted row exists, token is encrypted (not plaintext), and
        # the encrypted blob round-trips back to the broker payload.
        row = _read_integration(db_path, "gmail")
        assert row is not None
        assert "ca_abc123" not in row["auth_token_enc"]  # encrypted
        fernet = Fernet(os.environ["FERNET_KEY"].encode())
        decrypted = json.loads(
            fernet.decrypt(row["auth_token_enc"].encode()).decode()
        )
        assert decrypted["connected_account_id"] == "ca_abc123"
        assert decrypted["broker"] == "composio"
        # extra column carries the broker hint for ops visibility
        assert json.loads(row["extra"])["oauth_broker"] == "composio"

    def test_callback_rejects_invalid_state(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        resp = client.get(
            "/api/oauth/composio/callback",
            params={"state": "garbage", "connected_account_id": "ca_x"},
        )
        assert resp.status_code == 400
        assert resp.json()["detail"] == "invalid_state"

    def test_callback_rejects_missing_connected_account_id(
        self, client: TestClient, monkeypatch
    ) -> None:
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        state = self._start_and_get_state(client)
        resp = client.get(
            "/api/oauth/composio/callback", params={"state": state}
        )
        assert resp.status_code == 503  # provider says missing_callback_id
        assert "connected_account_id" in resp.json()["detail"]

    def test_re_authorize_updates_in_place(
        self, client: TestClient, db_path: str, monkeypatch
    ) -> None:
        """Re-running the OAuth dance for the same app updates rather than
        409s on the UNIQUE(app_name) constraint -- so users can rotate
        their Composio account without manual cleanup."""
        monkeypatch.setenv("ENABLE_COMPOSIO", "true")
        monkeypatch.setenv("COMPOSIO_API_KEY", "ck_dummy")
        state1 = self._start_and_get_state(client)
        client.get(
            "/api/oauth/composio/callback",
            params={"state": state1, "connected_account_id": "ca_first"},
        )
        state2 = self._start_and_get_state(client)
        resp = client.get(
            "/api/oauth/composio/callback",
            params={"state": state2, "connected_account_id": "ca_second"},
        )
        assert resp.status_code == 200, resp.text

        row = _read_integration(db_path, "gmail")
        fernet = Fernet(os.environ["FERNET_KEY"].encode())
        decrypted = json.loads(
            fernet.decrypt(row["auth_token_enc"].encode()).decode()
        )
        assert decrypted["connected_account_id"] == "ca_second"
