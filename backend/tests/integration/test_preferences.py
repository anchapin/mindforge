"""Test UserPreference API and onboarding endpoint — Task 7.

Run: pytest backend/tests/integration/test_preferences.py -v
"""

import os
import pathlib
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

# Patch os.makedirs BEFORE any backend imports
_original_makedirs = os.makedirs


def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)


os.makedirs = _patched_makedirs  # type: ignore[assignment]

_test_db_dir = tempfile.mkdtemp()
_test_db_path = os.path.join(_test_db_dir, "test.db")


def _init_test_db():
    conn = sqlite3.connect(_test_db_path)
    # Wrap DEFAULT expressions in parentheses — Python sqlite3 requires this for raw SQL
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_preference (
            id                  TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            proactive_monitoring_enabled INTEGER NOT NULL DEFAULT 1,
            email_check_interval_minutes INTEGER NOT NULL DEFAULT 30,
            calendar_check_interval_minutes INTEGER NOT NULL DEFAULT 60,
            billing_alert_threshold_usd INTEGER NOT NULL DEFAULT 50,
            notification_channel TEXT NOT NULL DEFAULT 'dashboard',
            notification_handle TEXT,
            onboarding_completed INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS writing_profile (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            tone TEXT NOT NULL DEFAULT 'semi-formal',
            sentence_length TEXT NOT NULL DEFAULT 'medium',
            first_person TEXT NOT NULL DEFAULT 'I',
            signature_phrases TEXT NOT NULL DEFAULT '[]',
            greeting_style TEXT NOT NULL DEFAULT 'Hi [Name],',
            signoff_style TEXT NOT NULL DEFAULT 'Cheers',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS integration (
            id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
            app_name TEXT NOT NULL UNIQUE,
            auth_token_enc TEXT NOT NULL,
            refresh_token_enc TEXT,
            token_key_id TEXT NOT NULL DEFAULT 'local',
            status TEXT NOT NULL DEFAULT 'active',
            last_sync_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            extra TEXT,
            permissions TEXT NOT NULL DEFAULT '[]',
            allowed_agents TEXT NOT NULL DEFAULT '[]'
        )
    """)
    # Singleton rows
    conn.execute("INSERT OR IGNORE INTO user_preference (id) VALUES (lower(hex(randomblob(16))))")
    conn.execute("INSERT OR IGNORE INTO writing_profile (id) VALUES (lower(hex(randomblob(16))))")
    conn.commit()
    conn.close()


_init_test_db()


class TestGetPreferences:
    """GET /api/preferences returns the UserPreference singleton."""

    @pytest.mark.asyncio
    async def test_get_preferences_returns_singleton_defaults(self):
        """GET /api/preferences returns all preference fields with defaults.

        RED: FAIL — preferences.py does not exist yet.
        GREEN: Implement GET /api/preferences returning UserPreference singleton.
        """
        from backend.api.routes import preferences as prefs_module

        test_conn = sqlite3.connect(_test_db_path)
        test_conn.row_factory = sqlite3.Row

        try:
            result = prefs_module.get_preferences(db=test_conn)
        except AttributeError as exc:
            pytest.fail(f"get_preferences not implemented: {exc}")

        # Should return all preference fields
        assert "proactive_monitoring_enabled" in result
        assert "email_check_interval_minutes" in result
        assert "calendar_check_interval_minutes" in result
        assert "billing_alert_threshold_usd" in result
        assert "notification_channel" in result
        assert "notification_handle" in result

        # Default values per schema
        assert result["proactive_monitoring_enabled"] == 1
        assert result["email_check_interval_minutes"] == 30
        assert result["calendar_check_interval_minutes"] == 60
        assert result["billing_alert_threshold_usd"] == 50
        assert result["notification_channel"] == "dashboard"

        test_conn.close()

    @pytest.mark.asyncio
    async def test_get_preferences_returns_stored_values(self):
        """GET /api/preferences returns user-updated values, not defaults.

        RED: FAIL — preferences not persisted.
        GREEN: SELECT from user_preference table, return stored values.
        """
        from backend.api.routes import preferences as prefs_module

        # Update a preference directly in DB — scoped to this test
        # Use ONLY proactive_monitoring_enabled to avoid polluting other field defaults
        conn = sqlite3.connect(_test_db_path)
        conn.execute(
            "UPDATE user_preference SET proactive_monitoring_enabled = 0, "
            "email_check_interval_minutes = 15",
        )
        conn.commit()
        conn.close()

        test_conn = sqlite3.connect(_test_db_path)
        test_conn.row_factory = sqlite3.Row

        try:
            result = prefs_module.get_preferences(db=test_conn)
        except AttributeError as exc:
            pytest.fail(f"get_preferences not implemented: {exc}")

        assert result["proactive_monitoring_enabled"] == 0
        assert result["email_check_interval_minutes"] == 15
        # Do NOT assert billing_alert_threshold_usd here — keep it pristine for put tests

        test_conn.close()


class TestPutPreferences:
    """PUT /api/preferences performs partial update of UserPreference singleton."""

    @pytest.mark.asyncio
    async def test_put_preferences_partial_update(self):
        """PUT /api/preferences updates only the sent fields.

        RED: FAIL — PUT endpoint not implemented.
        GREEN: Implement PUT /api/preferences with partial update logic.
        """
        from backend.api.routes import preferences as prefs_module
        from backend.api.routes.preferences import PreferencesUpdate

        test_conn = sqlite3.connect(_test_db_path)
        test_conn.row_factory = sqlite3.Row

        payload = PreferencesUpdate(
            proactive_monitoring_enabled=False,
            email_check_interval_minutes=45,
        )

        try:
            result = prefs_module.update_preferences(payload=payload, db=test_conn)
        except AttributeError as exc:
            pytest.fail(f"update_preferences not implemented: {exc}")

        assert result["status"] == "updated"
        assert result["preferences"]["proactive_monitoring_enabled"] == 0  # False stored as 0
        assert result["preferences"]["email_check_interval_minutes"] == 45
        # Unchanged fields stay at defaults
        assert result["preferences"]["calendar_check_interval_minutes"] == 60
        assert result["preferences"]["billing_alert_threshold_usd"] == 50

        test_conn.close()

    @pytest.mark.asyncio
    async def test_put_preferences_updates_persisted(self):
        """PUT /api/preferences changes survive a subsequent GET.

        RED: FAIL — preferences not written to DB.
        GREEN: UPDATE user_preference SET ... WHERE id = (SELECT id FROM user_preference).
        """
        from backend.api.routes import preferences as prefs_module
        from backend.api.routes.preferences import PreferencesUpdate

        test_conn = sqlite3.connect(_test_db_path)
        test_conn.row_factory = sqlite3.Row

        payload = PreferencesUpdate(billing_alert_threshold_usd=200)

        try:
            prefs_module.update_preferences(payload=payload, db=test_conn)
        except AttributeError as exc:
            pytest.fail(f"update_preferences not implemented: {exc}")

        # Verify persisted
        row = test_conn.execute("SELECT billing_alert_threshold_usd FROM user_preference").fetchone()
        assert row["billing_alert_threshold_usd"] == 200

        test_conn.close()


class TestOnboarding:
    """POST /api/onboarding accepts {writing_style, integrations} and creates records."""

    @pytest.mark.asyncio
    async def test_onboarding_creates_writing_profile(self):
        """POST /api/onboarding inserts writing_style fields into writing_profile.

        RED: FAIL — onboarding.py does not exist.
        GREEN: Implement POST /api/onboarding writing style creation.
        """
        from backend.api.routes import onboarding as onboard_module

        test_conn = sqlite3.connect(_test_db_path)
        test_conn.row_factory = sqlite3.Row

        class WritingStyle:
            tone = "casual"
            sentence_length = "short"
            first_person = "I"
            signature_phrases = ["cheers", "all the best"]
            greeting_style = "Hey team,"
            signoff_style = "Thanks"

        class Integrations:
            integrations = []

        class OnboardingPayload:
            writing_style = WritingStyle()
            integrations = []

        try:
            result = onboard_module.complete_onboarding(payload=OnboardingPayload(), db=test_conn)
        except AttributeError as exc:
            pytest.fail(f"complete_onboarding not implemented: {exc}")

        assert result["status"] == "created"

        # Verify writing profile was created
        row = test_conn.execute(
            "SELECT tone, greeting_style, signoff_style FROM writing_profile"
        ).fetchone()
        assert row["tone"] == "casual"
        assert row["greeting_style"] == "Hey team,"
        assert row["signoff_style"] == "Thanks"

        test_conn.close()

    @pytest.mark.asyncio
    async def test_onboarding_creates_integrations(self):
        """POST /api/onboarding encrypts and stores integration credentials.

        RED: FAIL — onboarding doesn't handle integrations.
        GREEN: Encrypt tokens with Fernet, insert into integrations table.
        """
        from backend.api.routes import onboarding as onboard_module

        test_conn = sqlite3.connect(_test_db_path)
        test_conn.row_factory = sqlite3.Row

        payload = onboard_module.OnboardingPayload(
            writing_style=onboard_module.WritingStyleInput(
                tone="semi-formal",
                sentence_length="medium",
                first_person="I",
                signature_phrases=[],
                greeting_style="Hi team,",
                signoff_style="Cheers",
            ),
            integrations=[
                onboard_module.IntegrationInput(
                    app_name="github",
                    token="ghp_testtoken123",
                    permissions=["repo"],
                    allowed_agents=["engineer"],
                )
            ],
        )

        with patch("backend.api.routes.onboarding._encrypt_token") as mock_encrypt:
            mock_encrypt.return_value = "encrypted_token"

            try:
                result = onboard_module.complete_onboarding(payload=payload, db=test_conn)
            except AttributeError as exc:
                pytest.fail(f"complete_onboarding not implemented: {exc}")

        assert result["status"] == "created"

        # Verify integration was stored
        row = test_conn.execute(
            "SELECT app_name, auth_token_enc, permissions FROM integration"
        ).fetchone()
        assert row["app_name"] == "github"
        # Permissions stored as JSON string via json.dumps()
        assert row["permissions"] == '["repo"]'

        test_conn.close()

    @pytest.mark.asyncio
    async def test_onboarding_updates_existing_records(self):
        """POST /api/onboarding updates existing writing_profile / integration if already exists.

        RED: FAIL — onboarding doesn't handle existing records (upsert).
        GREEN: INSERT OR REPLACE INTO writing_profile (id, ...) VALUES ((SELECT id...), ...).
        """
        from backend.api.routes import onboarding as onboard_module

        # Clean up any pre-existing github row from prior tests in the suite
        conn = sqlite3.connect(_test_db_path)
        conn.execute("DELETE FROM integration WHERE app_name = 'github'")
        conn.commit()
        conn.close()

        # Pre-existing integration — committed so complete_onboarding can see it
        conn = sqlite3.connect(_test_db_path)
        conn.execute(
            "INSERT INTO integration (id, app_name, auth_token_enc, permissions, allowed_agents, status, created_at, updated_at) "
            "VALUES (lower(hex(randomblob(16))), 'github', 'old_token', '[]', '[]', 'active', datetime('now'), datetime('now'))"
        )
        conn.commit()
        conn.close()

        test_conn = sqlite3.connect(_test_db_path)
        test_conn.row_factory = sqlite3.Row

        payload = onboard_module.OnboardingPayload(
            writing_style=onboard_module.WritingStyleInput(
                tone="formal",
                sentence_length="long",
                first_person="We",
                signature_phrases=["kind regards"],
                greeting_style="Dear team,",
                signoff_style="Regards",
            ),
            integrations=[
                onboard_module.IntegrationInput(
                    app_name="github",
                    token="ghp_newtoken456",
                    permissions=["repo", "workflow"],
                    allowed_agents=["engineer", "coo"],
                )
            ],
        )

        with patch("backend.api.routes.onboarding._encrypt_token") as mock_encrypt:
            mock_encrypt.return_value = "new_encrypted"

            try:
                result = onboard_module.complete_onboarding(payload=payload, db=test_conn)
            except AttributeError as exc:
                pytest.fail(f"complete_onboarding not implemented: {exc}")

        assert result["status"] == "created"

        # github integration should be updated, not duplicated
        rows = test_conn.execute("SELECT app_name FROM integration").fetchall()
        github_count = sum(1 for r in rows if r["app_name"] == "github")
        assert github_count == 1, f"Expected 1 github integration, got {github_count}"

        test_conn.close()
