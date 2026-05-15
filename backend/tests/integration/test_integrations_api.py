"""Integration tests for /api/integrations (issue #38).

Two regressions covered:
  1. Routes used `db` as a plain positional arg with no Depends(db_dep), so
     FastAPI treated it as a query parameter and every request 4xx'd.
  2. Routes targeted table `integrations` (plural); the schema defines
     `integration` (singular). Every query raised OperationalError.

These tests use FastAPI's TestClient with `app.dependency_overrides` so the
real Depends wiring is exercised end-to-end against an isolated SQLite DB.
"""

from __future__ import annotations

# ----- pre-import patches (must run before any `backend.*` import) ----------
import os
import pathlib
import tempfile

from cryptography.fernet import Fernet

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())

# deps.py calls os.makedirs(DATA_DIR) at import time; redirect away from /app
_ORIGINAL_MAKEDIRS = os.makedirs


def _safe_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _ORIGINAL_MAKEDIRS(path, *args, **kwargs)


os.makedirs = _safe_makedirs  # type: ignore[assignment]
# ----------------------------------------------------------------------------

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
    """Apply just the integration table schema. Parens wrap DEFAULT exprs to
    satisfy the Python sqlite3 driver, which is stricter than PGLite."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_INTEGRATION_DDL)
    conn.commit()
    conn.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """A FastAPI TestClient mounted with just the integrations router and an
    overridden db_dep that returns an isolated SQLite connection."""
    from backend.api.deps import db_dep
    from backend.api.routes import integrations

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115 (lifecycle managed manually)
    tmp.close()
    _init_test_db(tmp.name)

    app = FastAPI()
    app.include_router(integrations.router)

    def _override_db_dep() -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(tmp.name)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[db_dep] = _override_db_dep

    with TestClient(app) as c:
        yield c

    os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Smoke / regression
# ---------------------------------------------------------------------------


class TestRouteWiring:
    """Pin the bug from #38: the routes must declare Depends(db_dep)."""

    def test_get_does_not_treat_db_as_query_param(self, client: TestClient) -> None:
        """Pre-fix: GET / returned 422 (missing required `db` query param).

        Post-fix: 200 with [] because the table is empty.
        """
        resp = client.get("/api/integrations/")
        assert resp.status_code == 200, resp.text
        assert resp.json() == []

    def test_post_does_not_422_on_missing_db_param(self, client: TestClient) -> None:
        """Pre-fix: POST / returned 422 because FastAPI required ?db=...

        Post-fix: 201 because Depends(db_dep) injects the connection.
        """
        resp = client.post(
            "/api/integrations/",
            json={"app_name": "github", "token": "ghp_fake"},
        )
        assert resp.status_code == 201, resp.text


# ---------------------------------------------------------------------------
# CRUD round-trip
# ---------------------------------------------------------------------------


class TestCRUDRoundTrip:
    def test_full_lifecycle(self, client: TestClient) -> None:
        # CREATE
        create = client.post(
            "/api/integrations/",
            json={
                "app_name": "stripe",
                "token": "sk_test_abc",
                "permissions": ["read"],
                "allowed_agents": ["coo", "cmo"],
            },
        )
        assert create.status_code == 201, create.text
        body = create.json()
        assert body["app_name"] == "stripe"
        assert body["status"] == "active"
        assert body["permissions"] == ["read"]
        assert body["allowed_agents"] == ["coo", "cmo"]
        # Token is never echoed back
        assert "token" not in body
        assert "auth_token_enc" not in body
        integration_id = body["id"]

        # LIST
        listed = client.get("/api/integrations/")
        assert listed.status_code == 200
        all_rows = listed.json()
        assert len(all_rows) == 1
        assert all_rows[0]["id"] == integration_id

        # TEST (probe)
        probe = client.post(f"/api/integrations/{integration_id}/test")
        assert probe.status_code == 200
        assert probe.json()["success"] is True

        # DELETE
        delete = client.delete(f"/api/integrations/{integration_id}")
        assert delete.status_code == 200
        assert delete.json()["status"] == "deleted"

        # Confirm gone
        listed = client.get("/api/integrations/")
        assert listed.json() == []


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrors:
    def test_delete_unknown_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/api/integrations/does-not-exist")
        assert resp.status_code == 404

    def test_test_unknown_returns_404(self, client: TestClient) -> None:
        resp = client.post("/api/integrations/does-not-exist/test")
        assert resp.status_code == 404

    def test_duplicate_app_name_returns_409(self, client: TestClient) -> None:
        first = client.post(
            "/api/integrations/", json={"app_name": "linear", "token": "lin_1"}
        )
        assert first.status_code == 201
        second = client.post(
            "/api/integrations/", json={"app_name": "linear", "token": "lin_2"}
        )
        assert second.status_code == 409

    def test_create_validates_payload(self, client: TestClient) -> None:
        resp = client.post("/api/integrations/", json={"app_name": "", "token": ""})
        assert resp.status_code == 422  # Pydantic min_length

    def test_table_name_is_singular(self) -> None:
        """Pin the second half of #38: SQL must target table `integration`,
        not `integrations`. Inspect the source so a future SQL typo also
        fails fast (not just at runtime via OperationalError)."""
        from backend.api.routes import integrations as routes_mod

        source = pathlib.Path(routes_mod.__file__).read_text()
        for keyword in ("FROM integrations", "INTO integrations", "DELETE FROM integrations"):
            assert keyword not in source, (
                f"Routes still reference legacy table name via '{keyword}'"
            )


# ---------------------------------------------------------------------------
# Token confidentiality
# ---------------------------------------------------------------------------


class TestTokenHandling:
    def test_token_is_never_echoed(self, client: TestClient) -> None:
        """Plaintext token must never appear in any list/get response."""
        client.post(
            "/api/integrations/",
            json={"app_name": "github", "token": "ghp_super_secret_value"},
        )
        listed = client.get("/api/integrations/").json()
        assert listed[0]["app_name"] == "github"
        assert "ghp_super_secret_value" not in str(listed)
