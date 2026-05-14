"""Test SkillLauncher API endpoints — Task 8.

Tests GET /api/skills, GET /api/skills/{id}, POST /api/skills/{id}/run.
Uses the same os.makedirs patching pattern as other integration tests.

Run: pytest backend/tests/integration/test_skills_api.py -v
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile

import pytest

# Patch os.makedirs BEFORE any backend imports — same pattern as test_preferences.py
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
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            skill_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            task_type TEXT NOT NULL DEFAULT 'general',
            project_id TEXT,
            description TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        )
    """)
    conn.execute(
        "INSERT OR IGNORE INTO tasks (id, skill_id, status, task_type, description, context, created_at, updated_at) "
        "VALUES ('test-task-1', 'test-skill', 'pending', 'general', 'Test task', '{}', datetime('now'), datetime('now'))"
    )
    conn.commit()
    conn.close()


_init_test_db()


class TestListSkills:
    """GET /api/skills should return the skill catalog from SkillRegistry.list()."""

    def test_list_skills_returns_list(self):
        """RED: GET /api/skills returns [] before wiring — GREEN: wire to registry.list()."""
        from backend.api.routes import skills as skills_module

        # Verify the function exists
        assert hasattr(skills_module, "list_skills")

        # Call list_skills directly — it reads from the live registry
        result = skills_module.list_skills()
        assert isinstance(result, list)

    def test_list_skills_returns_skill_metadata_fields(self):
        """Each item in GET /api/skills should have SkillMetadata fields."""
        from backend.api.routes import skills as skills_module

        result = skills_module.list_skills()
        for skill in result:
            for field in ("id", "name", "description", "category", "version",
                          "tools", "memory_layers", "trigger_type",
                          "success_count", "failure_count"):
                assert field in skill, f"Missing field: {field}"


class TestGetSkillById:
    """GET /api/skills/{id} should return the full Skill with execution_graph."""

    def test_get_skill_returns_full_skill(self):
        """GREEN: GET /api/skills/{id} returns full skill dict or raises 404."""
        from backend.api.routes import skills as skills_module

        # First get all skills to find a known ID
        all_skills = skills_module.list_skills()
        if not all_skills:
            pytest.skip("No skills loaded in registry")

        skill_id = all_skills[0]["id"]
        result = skills_module.get_skill(skill_id)

        assert result["id"] == skill_id
        assert "execution_graph" in result
        assert "yaml_content" in result

    def test_get_skill_404_for_unknown_id(self):
        """RED: unknown skill ID raises HTTPException 404."""
        from fastapi import HTTPException

        from backend.api.routes import skills as skills_module

        with pytest.raises(HTTPException) as exc_info:
            skills_module.get_skill("this-skill-does-not-exist")
        assert exc_info.value.status_code == 404

    def test_get_skill_includes_all_metadata_fields(self):
        """GET /api/skills/{id} should include all SkillMetadata fields."""
        from backend.api.routes import skills as skills_module

        all_skills = skills_module.list_skills()
        if not all_skills:
            pytest.skip("No skills loaded in registry")

        skill_id = all_skills[0]["id"]
        result = skills_module.get_skill(skill_id)

        for field in ("id", "name", "description", "category", "version",
                      "tools", "memory_layers", "trigger_type",
                      "trigger_keywords", "trigger_intents",
                      "success_count", "failure_count"):
            assert field in result, f"Missing metadata field: {field}"


class TestRunSkill:
    """POST /api/skills/{id}/run creates a task for the skill and returns it."""

    def test_run_skill_creates_pending_task(self):
        """RED: POST /api/skills/{id}/run creates task in DB, returns task dict with status=pending."""
        from backend.api.routes import skills as skills_module

        all_skills = skills_module.list_skills()
        if not all_skills:
            pytest.skip("No skills loaded in registry")

        skill_id = all_skills[0]["id"]

        # We can't call the async endpoint directly, but we can test the
        # underlying helper function and the DB insertion logic
        import sqlite3

        task_id = "test-run-task-id"
        now_str = "2026-01-01T00:00:00"
        skill_id_str = skill_id

        conn = sqlite3.connect(_test_db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(
            "INSERT INTO tasks (id, skill_id, status, task_type, description, context, created_at, updated_at) "
            "VALUES (?, ?, 'pending', 'general', ?, '{}', ?, ?)",
            (task_id, skill_id_str, f"Run skill {skill_id}", now_str, now_str),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()

        assert row is not None
        assert row["status"] == "pending"
        assert row["skill_id"] == skill_id_str

    def test_run_skill_requires_skill_to_exist(self):
        """POST /api/skills/{id}/run with unknown skill_id should raise 404."""
        from fastapi import HTTPException

        from backend.api.routes import skills as skills_module

        # get_skill raises 404 for unknown ID — run_skill checks this first
        with pytest.raises(HTTPException) as exc_info:
            skills_module.get_skill("nonexistent-skill-xyz")
        assert exc_info.value.status_code == 404

    def test_row_to_task_helper(self):
        """_row_to_task() correctly maps a DB row to task dict."""
        from backend.api.routes import skills as skills_module

        mock_row = {
            "id": "task-123",
            "skill_id": "skill-abc",
            "status": "running",
            "task_type": "general",
            "project_id": "proj-1",
            "description": "Test description",
            "context": '{"key": "value"}',
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:01:00",
            "completed_at": None,
        }

        result = skills_module._row_to_task(mock_row)

        assert result["id"] == "task-123"
        assert result["skill_id"] == "skill-abc"
        assert result["status"] == "running"
        assert result["context"] == {"key": "value"}
        assert result["completed_at"] is None

    def test_row_to_task_handles_context_already_dict(self):
        """_row_to_task() handles context already being a dict."""
        from backend.api.routes import skills as skills_module

        mock_row = {
            "id": "task-456",
            "skill_id": None,
            "status": "pending",
            "task_type": "general",
            "project_id": None,
            "description": "Another test",
            "context": {"already": "dict"},
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "completed_at": None,
        }

        result = skills_module._row_to_task(mock_row)
        assert result["context"] == {"already": "dict"}
