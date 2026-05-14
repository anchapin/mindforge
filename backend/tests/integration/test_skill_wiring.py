"""Test skill wiring — verify trigger_skill is called in _execute_task.

RED phase tests: confirm that current _execute_task does NOT call trigger_skill.
After GREEN fix, all 3 tests should pass.
"""

import os
import pathlib
import sqlite3
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Patch os.makedirs BEFORE any backend imports happen
_original_makedirs = os.makedirs
def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)

os.makedirs = _patched_makedirs  # type: ignore[assignment]

# Use a temp dir + db for tests
_test_db_dir = tempfile.mkdtemp()
_test_db_path = os.path.join(_test_db_dir, "test.db")


def _init_test_db():
    conn = sqlite3.connect(_test_db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            skill_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            task_type TEXT NOT NULL DEFAULT 'general',
            project_id TEXT,
            description TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT
        )
    """)
    conn.execute(
        "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test-task-1", None, "pending", "general", None, "do test action", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test-task-2", None, "pending", "general", None, "test something", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.execute(
        "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("test-task-3", None, "pending", "general", None, "generic task", "{}", "2026-01-01T00:00:00", "2026-01-01T00:00:00"),
    )
    conn.commit()
    conn.close()


_init_test_db()


@pytest.mark.asyncio
async def test_execute_task_calls_trigger_skill_with_description():
    """_execute_task should call trigger_skill(task_description) before supervisor.

    RED: FAILS - trigger_skill is never called. _execute_task goes straight to
    SupervisorRunner.run() without ever invoking the skill trigger.
    """
    from backend.api.routes import tasks as tasks_module

    trigger_called_with = []

    async def mock_trigger(task_desc, llm_router=None):
        trigger_called_with.append(task_desc)
        return None  # No skill matched

    async def mock_supervisor_run(self, task_description, **kwargs):
        return MagicMock(error=None, context={}, result={}, agent_role="supervisor")

    with (
        patch("backend.api.routes.tasks.trigger_skill", mock_trigger),
        patch("backend.api.routes.tasks.SupervisorRunner.run", mock_supervisor_run),
        patch("backend.api.deps.DB_PATH", _test_db_path),
        patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
    ):
        mock_memory = MagicMock()
        mock_memory.write_episodic = AsyncMock()

        await tasks_module._execute_task(
            task_id="test-task-1",
            description="do test action",
            project_id=None,
            memory=mock_memory,
        )

    # This is the P0 bug: trigger_skill is never called
    assert len(trigger_called_with) == 1, f"trigger_skill was called {len(trigger_called_with)} times, expected 1. Call args: {trigger_called_with}"
    assert trigger_called_with[0] == "do test action"


@pytest.mark.asyncio
async def test_execute_task_calls_execute_skill_when_skill_matches():
    """When trigger_skill returns a skill, execute_skill should be called instead of supervisor.

    RED: FAILS - _execute_task has NO logic to route to execute_skill.
    Even if trigger_skill returns a skill, supervisor.run is still called.
    """
    from backend.api.routes import tasks as tasks_module
    from backend.skills.registry import get_registry

    registry = get_registry()
    skills = registry.list()
    sample_skill = skills[0] if skills else None

    if sample_skill is None:
        pytest.skip("No skills loaded in registry")

    execute_skill_called = []

    async def mock_trigger(task_desc, llm_router=None):
        return sample_skill  # Skill matched!

    async def mock_execute_skill(skill, task_id, llm_complete, tools, initial_context=None):
        execute_skill_called.append(skill.id)
        return MagicMock(skill_id=skill.id, status="completed", nodes_completed=[])

    async def mock_supervisor_run(self, task_description, **kwargs):
        return MagicMock(error=None)

    with (
        patch("backend.api.routes.tasks.trigger_skill", mock_trigger),
        patch("backend.skills.executor.execute_skill", mock_execute_skill),
        patch("backend.api.routes.tasks.SupervisorRunner.run", mock_supervisor_run),
        patch("backend.api.deps.DB_PATH", _test_db_path),
        patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
    ):
        mock_memory = MagicMock()
        mock_memory.write_episodic = AsyncMock()

        await tasks_module._execute_task(
            task_id="test-task-2",
            description="test something",
            project_id=None,
            memory=mock_memory,
        )

    # execute_skill should be called, NOT supervisor.run
    assert len(execute_skill_called) == 1, f"execute_skill called {len(execute_skill_called)} times, expected 1. supervisor was called instead."
    assert execute_skill_called[0] == sample_skill.id


@pytest.mark.asyncio
async def test_execute_task_falls_back_to_supervisor_when_no_skill():
    """When trigger_skill returns None, supervisor.run should be called.

    GREEN: PASSES - this is the current (broken) behavior.
    """
    from backend.api.routes import tasks as tasks_module

    supervisor_called = False

    async def mock_trigger(task_desc, llm_router=None):
        return None  # No skill matched

    async def mock_supervisor_run(self, task_description, **kwargs):
        nonlocal supervisor_called
        supervisor_called = True
        return MagicMock(error=None, context={}, result={}, agent_role="supervisor")

    with (
        patch("backend.api.routes.tasks.trigger_skill", mock_trigger),
        patch("backend.api.routes.tasks.SupervisorRunner.run", mock_supervisor_run),
        patch("backend.api.deps.DB_PATH", _test_db_path),
        patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
    ):
        mock_memory = MagicMock()
        mock_memory.write_episodic = AsyncMock()

        await tasks_module._execute_task(
            task_id="test-task-3",
            description="generic task",
            project_id=None,
            memory=mock_memory,
        )

    assert supervisor_called, "supervisor.run should be called when no skill matches"
