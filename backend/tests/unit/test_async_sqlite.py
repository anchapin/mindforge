"""Unit tests for async SQLite operations in episodic and style stores.

Tests that:
1. AsyncSQLitePool correctly manages connections
2. EpisodicMemoryStore async methods work correctly
3. WritingProfileStore async methods work correctly
4. No sync sqlite3.connect calls remain in the async path
"""

from __future__ import annotations

import os
import pathlib
import sys
import uuid
from datetime import datetime

import pytest

# Patch os.makedirs BEFORE any imports that would use it.
# The memory stores call os.makedirs for their DB directories,
# which would fail in the test environment without this patch.
_original_makedirs = os.makedirs
def _patched_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    # Allow creation of temp directories but not /app
    if str(path).startswith("/app"):
        return
    return _original_makedirs(path, *args, **kwargs)

os.makedirs = _patched_makedirs  # type: ignore[assignment]

# Add backend/ to path so 'from memory.episodic import ...' resolves correctly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'backend'))

from memory.episodic import AsyncSQLitePool, EpisodicMemory, EpisodicMemoryStore  # noqa: E402
from memory.style import WritingProfileStore  # noqa: E402


class TestAsyncSQLitePool:
    """Tests for AsyncSQLitePool connection management."""

    @pytest.mark.asyncio
    async def test_pool_initialization(self, tmp_path):
        """Pool starts and creates connections."""
        db_path = str(tmp_path / "test_pool.db")
        pool = AsyncSQLitePool(db_path, pool_size=2)
        await pool.start()
        assert pool._started is True
        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_connection_reuse(self, tmp_path):
        """Connections are reused from the pool."""
        db_path = str(tmp_path / "test_reuse.db")
        pool = AsyncSQLitePool(db_path, pool_size=2)
        await pool.start()

        # Execute two queries — should reuse connections
        await pool.execute("CREATE TABLE IF NOT EXISTS test (id TEXT PRIMARY KEY)", ())
        await pool.execute("INSERT INTO test (id) VALUES (?)", ("test1",))

        # Second query should work (connection still valid)
        rows = await pool.execute("SELECT * FROM test", ())
        assert len(rows) == 1
        assert rows[0]["id"] == "test1"

        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_execute_write(self, tmp_path):
        """execute_write returns correct rowcount."""
        db_path = str(tmp_path / "test_write.db")
        pool = AsyncSQLitePool(db_path, pool_size=2)
        await pool.start()

        await pool.execute_write(
            "CREATE TABLE IF NOT EXISTS test_write (id TEXT PRIMARY KEY)",
            (),
        )
        rowcount = await pool.execute_write(
            "INSERT INTO test_write (id) VALUES (?)",
            ("w1",),
        )
        assert rowcount == 1

        rowcount = await pool.execute_write(
            "UPDATE test_write SET id = ? WHERE id = ?",
            ("w2", "w1"),
        )
        assert rowcount == 1

        await pool.stop()

    @pytest.mark.asyncio
    async def test_pool_execute_one(self, tmp_path):
        """execute_one returns single row or None."""
        db_path = str(tmp_path / "test_one.db")
        pool = AsyncSQLitePool(db_path, pool_size=2)
        await pool.start()

        await pool.execute_write(
            "CREATE TABLE IF NOT EXISTS test_one (id TEXT PRIMARY KEY, val TEXT)",
            (),
        )
        await pool.execute_write(
            "INSERT INTO test_one (id, val) VALUES (?, ?)",
            ("row1", "value1"),
        )

        row = await pool.execute_one("SELECT * FROM test_one WHERE id = ?", ("row1",))
        assert row is not None
        assert row["id"] == "row1"
        assert row["val"] == "value1"

        missing = await pool.execute_one("SELECT * FROM test_one WHERE id = ?", ("nonexistent",))
        assert missing is None

        await pool.stop()


class TestEpisodicMemoryStoreAsync:
    """Tests for async EpisodicMemoryStore operations."""

    @pytest.mark.asyncio
    async def test_insert_and_query(self, tmp_path):
        """Can insert a record and query it back."""
        db_path = str(tmp_path / "episodic_test.db")
        store = EpisodicMemoryStore(db_path)
        await store.start()

        record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id="proj-1",
            task_id="task-1",
            task_type="engineering",
            agent_role="engineer",
            summary="Fixed a bug in async sqlite",
            outcome_status="completed",
            created_at=datetime.utcnow(),
        )
        await store.insert(record)

        results = await store.query_by_project("proj-1")
        assert len(results) == 1
        assert results[0].id == record.id
        assert results[0].task_type == "engineering"

        await store.stop()

    @pytest.mark.asyncio
    async def test_query_by_project_filter(self, tmp_path):
        """query_by_project correctly filters by project_id."""
        db_path = str(tmp_path / "episodic_filter.db")
        store = EpisodicMemoryStore(db_path)
        await store.start()

        for i in range(3):
            record = EpisodicMemory(
                id=str(uuid.uuid4()),
                project_id="proj-1" if i % 2 == 0 else "proj-2",
                task_id=f"task-{i}",
                task_type="general",
                agent_role="coo",
                summary=f"Task {i}",
                outcome_status="completed",
            )
            await store.insert(record)

        results_proj1 = await store.query_by_project("proj-1")
        assert len(results_proj1) == 2

        results_proj2 = await store.query_by_project("proj-2")
        assert len(results_proj2) == 1

        await store.stop()

    @pytest.mark.asyncio
    async def test_delete(self, tmp_path):
        """Delete removes record and returns rowcount."""
        db_path = str(tmp_path / "episodic_delete.db")
        store = EpisodicMemoryStore(db_path)
        await store.start()

        record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=None,
            task_id="task-del",
            task_type="general",
            agent_role="coo",
            summary="Will be deleted",
            outcome_status="completed",
        )
        await store.insert(record)

        rowcount = await store.delete(record.id)
        assert rowcount == 1

        # Second delete returns 0
        rowcount = await store.delete(record.id)
        assert rowcount == 0

        await store.stop()

    @pytest.mark.asyncio
    async def test_delete_older_than(self, tmp_path):
        """delete_older_than correctly removes old records."""
        db_path = str(tmp_path / "episodic_old.db")
        store = EpisodicMemoryStore(db_path)
        await store.start()

        # Insert with old date
        old_record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=None,
            task_id="old-task",
            task_type="general",
            agent_role="coo",
            summary="Old record",
            outcome_status="completed",
            created_at=datetime(2020, 1, 1),
        )
        await store.insert(old_record)

        # With default 180-day retention, old record should be deleted
        deleted = await store.delete_older_than(days=180)
        # Since record is older than 180 days, it should be deleted
        assert deleted >= 1

        await store.stop()

    @pytest.mark.asyncio
    async def test_get_task_id(self, tmp_path):
        """get_task_id returns correct task_id for record."""
        db_path = str(tmp_path / "episodic_taskid.db")
        store = EpisodicMemoryStore(db_path)
        await store.start()

        record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=None,
            task_id="expected-task-id-123",
            task_type="general",
            agent_role="coo",
            summary="Test",
            outcome_status="completed",
        )
        await store.insert(record)

        task_id = await store.get_task_id(record.id)
        assert task_id == "expected-task-id-123"

        missing = await store.get_task_id("nonexistent-id")
        assert missing is None

        await store.stop()


class TestWritingProfileStoreAsync:
    """Tests for async WritingProfileStore operations."""

    @pytest.mark.asyncio
    async def test_get_default_profile(self, tmp_path):
        """get() returns profile with spec defaults."""
        db_path = str(tmp_path / "style_profile.db")
        store = WritingProfileStore(db_path)
        await store.start()

        profile = await store.get()
        assert profile.tone == "semi-formal"
        assert profile.sentence_length == "medium"
        assert profile.first_person == "I"
        assert profile.signature_phrases == []
        assert profile.greeting_style == "Hi [Name],"
        assert profile.signoff_style == "Cheers"

        await store.stop()

    @pytest.mark.asyncio
    async def test_update_style_partial(self, tmp_path):
        """update_style supports partial updates."""
        db_path = str(tmp_path / "style_update.db")
        store = WritingProfileStore(db_path)
        await store.start()

        updated = await store.update_style({"tone": "casual"})
        assert updated.tone == "casual"
        # Other fields unchanged
        assert updated.sentence_length == "medium"
        assert updated.greeting_style == "Hi [Name],"

        await store.stop()

    @pytest.mark.asyncio
    async def test_reset_profile(self, tmp_path):
        """reset() restores spec defaults."""
        db_path = str(tmp_path / "style_reset.db")
        store = WritingProfileStore(db_path)
        await store.start()

        await store.update_style({"tone": "formal", "greeting_style": "Dear,"})
        profile = await store.reset()

        assert profile.tone == "semi-formal"
        assert profile.greeting_style == "Hi [Name],"

        await store.stop()

    @pytest.mark.asyncio
    async def test_format(self, tmp_path):
        """format() returns style guide string."""
        db_path = str(tmp_path / "style_format.db")
        store = WritingProfileStore(db_path)
        await store.start()

        await store.update_style({
            "tone": "formal",
            "first_person": "we",
            "signature_phrases": ["best regards"],
        })

        formatted = await store.format()
        assert "Tone: formal" in formatted
        assert 'First person: "we"' in formatted
        assert '"best regards"' in formatted

        await store.stop()


class TestNoSyncSqliteInAsyncContext:
    """Verify no sync sqlite calls exist in async memory stores."""

    def test_episodic_store_has_no_sqlite3_import(self):
        """episodic.py should not import sqlite3 directly for sync operations."""
        # Check module source doesn't have sync sqlite3 usage
        import inspect

        import memory.episodic as episodic_module
        source = inspect.getsource(episodic_module)

        # Should use aiosqlite.connect, not sqlite3.connect
        assert "sqlite3.connect" not in source, \
            "episodic.py should use aiosqlite, not sqlite3.connect"

    def test_style_store_has_no_sqlite3_import(self):
        """style.py should not import sqlite3 directly for sync operations."""
        import inspect

        import memory.style as style_module
        source = inspect.getsource(style_module)

        # Should use aiosqlite.connect, not sqlite3.connect
        assert "sqlite3.connect" not in source, \
            "style.py should use aiosqlite, not sqlite3.connect"
