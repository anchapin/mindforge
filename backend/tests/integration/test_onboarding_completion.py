"""Integration tests for the #72 onboarding completion fix.

Pre-fix bugs:
  1. POST /api/onboarding wrote profile/integrations but never set any
     'I'm done' flag. The frontend first-run gate keyed off prefs.id == ''
     which never fired in production (the singleton row is created at
     first migration, so id is always a real UUID).
  2. POST /api/onboarding targeted table 'integrations' (plural) — the
     same bug as #38 fixed in routes/integrations.py. Every onboarding
     POST raised OperationalError.

Post-fix:
  - schema.sql gains user_preference.onboarding_completed (default 0)
  - backend/db/migrate.py adds the column to existing alpha installs via
    a small in-place migration helper
  - POST /api/onboarding sets onboarding_completed = 1 + uses the
    canonical table name 'integration'
  - POST /api/onboarding/skip sets the flag without writing any data
  - GET /api/preferences returns onboarding_completed
"""

from __future__ import annotations

# ----- pre-import patches -------------------------------------------------
import os
import pathlib

_ORIGINAL_MAKEDIRS = os.makedirs


def _safe_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _ORIGINAL_MAKEDIRS(path, *args, **kwargs)


os.makedirs = _safe_makedirs  # type: ignore[assignment]

from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("FERNET_KEY", Fernet.generate_key().decode())
# --------------------------------------------------------------------------

import sqlite3  # noqa: E402
import tempfile  # noqa: E402
from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# Inline DDL for just the tables this test exercises. Mirrors test_integrations_api.py
# pattern (the full schema.sql isn't compatible with sqlite3.executescript).
_DDL = """
CREATE TABLE IF NOT EXISTS user_preference (
    id                                   TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    proactive_monitoring_enabled          INTEGER NOT NULL DEFAULT 1,
    email_check_interval_minutes          INTEGER NOT NULL DEFAULT 30,
    calendar_check_interval_minutes       INTEGER NOT NULL DEFAULT 60,
    billing_alert_threshold_usd           INTEGER NOT NULL DEFAULT 50,
    notification_channel                  TEXT NOT NULL DEFAULT 'dashboard',
    notification_handle                   TEXT,
    onboarding_completed                  INTEGER NOT NULL DEFAULT 0,
    created_at                           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at                           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS writing_profile (
    id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    tone                TEXT NOT NULL DEFAULT 'semi-formal',
    sentence_length     TEXT NOT NULL DEFAULT 'medium',
    first_person        TEXT NOT NULL DEFAULT 'I',
    signature_phrases   TEXT NOT NULL DEFAULT '[]',
    greeting_style      TEXT NOT NULL DEFAULT 'Hi [Name],',
    signoff_style       TEXT NOT NULL DEFAULT 'Cheers',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

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

INSERT OR IGNORE INTO user_preference (id) VALUES (lower(hex(randomblob(16))));
"""


@pytest.fixture
def client() -> Iterator[TestClient]:
    from backend.api.deps import db_dep
    from backend.api.routes import onboarding, preferences

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(_DDL)
    conn.commit()
    conn.close()

    app = FastAPI()
    app.include_router(onboarding.router)
    app.include_router(preferences.router)

    def _override_db_dep() -> Iterator[sqlite3.Connection]:
        c = sqlite3.connect(tmp.name, check_same_thread=False)
        c.row_factory = sqlite3.Row
        try:
            yield c
        finally:
            c.close()

    app.dependency_overrides[db_dep] = _override_db_dep

    with TestClient(app) as c:
        yield c

    os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# The bug: POST /api/onboarding must set onboarding_completed
# ---------------------------------------------------------------------------


class TestCompletionFlag:
    def test_initial_state_is_not_onboarded(self, client: TestClient) -> None:
        resp = client.get("/api/preferences/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["onboarding_completed"] is False, (
            "Fresh install must report onboarding_completed=False"
        )

    def test_post_onboarding_flips_the_flag(self, client: TestClient) -> None:
        post = client.post(
            "/api/onboarding/",
            json={
                "writing_style": {"tone": "casual"},
                "integrations": [],
            },
        )
        assert post.status_code == 200, post.text
        body = post.json()
        assert body["onboarding_completed"] is True

        # And GET reflects it
        get = client.get("/api/preferences/")
        assert get.json()["onboarding_completed"] is True

    def test_skip_endpoint_flips_the_flag_without_writing_data(
        self, client: TestClient
    ) -> None:
        resp = client.post("/api/onboarding/skip")
        assert resp.status_code == 200
        body = resp.json()
        assert body["onboarding_completed"] is True
        assert body["status"] == "skipped"

        get = client.get("/api/preferences/")
        assert get.json()["onboarding_completed"] is True


# ---------------------------------------------------------------------------
# Pre-fix #2: table name fix (the silent OperationalError)
# ---------------------------------------------------------------------------


class TestIntegrationTableName:
    def test_post_with_integrations_persists_to_singular_table(
        self, client: TestClient
    ) -> None:
        post = client.post(
            "/api/onboarding/",
            json={
                "writing_style": {},
                "integrations": [
                    {
                        "app_name": "github",
                        "token": "ghp_test_value",
                        "permissions": ["read"],
                        "allowed_agents": ["engineer"],
                    }
                ],
            },
        )
        # Pre-fix this raised OperationalError on 'integrations' (plural).
        assert post.status_code == 200, post.text

    def test_source_no_longer_references_legacy_plural_name(self) -> None:
        from backend.api.routes import onboarding as routes_mod

        source = pathlib.Path(routes_mod.__file__).read_text()
        for keyword in (
            "FROM integrations",
            "INTO integrations",
            "UPDATE integrations",
        ):
            assert keyword not in source, (
                f"onboarding.py still references legacy table name via '{keyword}'"
            )


# ---------------------------------------------------------------------------
# In-place column-add migration for existing alpha installs
# ---------------------------------------------------------------------------


class TestInPlaceMigration:
    def test_add_column_runs_when_missing(self, tmp_path) -> None:
        """Simulate an alpha install that has user_preference WITHOUT the
        new column. The migration helper must add it idempotently."""
        from backend.db.migrate import _apply_inplace_column_additions

        db_path = tmp_path / "legacy.db"
        conn = sqlite3.connect(str(db_path))
        # Old schema (no onboarding_completed column)
        conn.executescript("""
            CREATE TABLE user_preference (
                id TEXT PRIMARY KEY,
                proactive_monitoring_enabled INTEGER NOT NULL DEFAULT 1
            );
            INSERT INTO user_preference (id) VALUES ('singleton');
        """)
        conn.commit()

        # Pre-condition: column missing
        cols = {row[1] for row in conn.execute("PRAGMA table_info(user_preference)")}
        assert "onboarding_completed" not in cols

        _apply_inplace_column_additions(conn)
        conn.commit()

        # Post-condition: column added with default 0
        cols = {row[1] for row in conn.execute("PRAGMA table_info(user_preference)")}
        assert "onboarding_completed" in cols
        row = conn.execute(
            "SELECT onboarding_completed FROM user_preference WHERE id = 'singleton'"
        ).fetchone()
        assert row[0] == 0

        conn.close()

    def test_add_column_is_idempotent(self, tmp_path) -> None:
        """Running the migration twice on the same DB shouldn't error."""
        from backend.db.migrate import _apply_inplace_column_additions

        db_path = tmp_path / "current.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(_DDL)
        conn.commit()

        # Should be a no-op (column already exists from _DDL)
        _apply_inplace_column_additions(conn)
        _apply_inplace_column_additions(conn)
        conn.commit()
        conn.close()

    def test_skips_when_table_doesnt_exist(self, tmp_path) -> None:
        """A brand-new DB without any tables should be left alone."""
        from backend.db.migrate import _apply_inplace_column_additions

        db_path = tmp_path / "fresh.db"
        conn = sqlite3.connect(str(db_path))
        # No schema applied yet
        _apply_inplace_column_additions(conn)
        # Should not raise; should not have created the table either
        tables = [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        assert "user_preference" not in tables
        conn.close()
