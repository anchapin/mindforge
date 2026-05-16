"""Episodic memory — structured task history stored in PGLite (async).

From SPEC.md §2.2 and §5.7.
Stores completed task records enabling "what did we do last week?" queries.
180-day rolling retention window.

Uses aiosqlite for non-blocking async I/O with a connection pool.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------------------


class AsyncSQLitePool:
    """Async connection pool for SQLite using aiosqlite.

    Maintains a pool of connections to avoid the overhead of creating
    new connections for each operation. Connections are shared across
    all database operations.
    """

    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Initialize the connection pool."""
        if self._started:
            return
        async with self._lock:
            if self._started:
                return
            for _ in range(self.pool_size):
                conn = await _ai_sqlite_connect(self.db_path)
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA busy_timeout=5000")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await self._pool.put(conn)
            self._started = True
            logger.info("AsyncSQLitePool started with %d connections", self.pool_size)

    async def stop(self) -> None:
        """Close all connections in the pool."""
        if not self._started:
            return
        async with self._lock:
            if not self._started:
                return
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    await conn.close()
                except asyncio.QueueEmpty:
                    break
            self._started = False
            logger.info("AsyncSQLitePool stopped")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[ai_sqlite_Connection]:
        """Acquire a connection from the pool."""
        if not self._started:
            await self.start()
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def execute(self, query: str, params: tuple = ()) -> list[dict]:
        """Execute a query and return all rows as dicts."""
        async with self.acquire() as conn:
            conn.row_factory = _dict_row_factory
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return rows

    async def execute_one(self, query: str, params: tuple = ()) -> dict | None:
        """Execute a query and return a single row as dict."""
        async with self.acquire() as conn:
            conn.row_factory = _dict_row_factory
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            return row if row else None

    async def execute_write(self, query: str, params: tuple = ()) -> int:
        """Execute a write query and return rowcount."""
        async with self.acquire() as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor.rowcount


# aiosqlite types (we use the installed aiosqlite package)
ai_sqlite_Connection = Any  # aiosqlite.Connection


async def _ai_sqlite_connect(db_path: str) -> ai_sqlite_Connection:
    """Connect to SQLite using aiosqlite for async operations."""
    import aiosqlite
    return await aiosqlite.connect(db_path)


def _dict_row_factory(cursor: Any, row: tuple) -> dict:
    """Convert a sqlite row to a dict using column names."""
    # aiosqlite uses cursor.column_names; sqlite3 uses cursor.description
    if hasattr(cursor, 'column_names'):
        col_names = cursor.column_names
    else:
        col_names = [d[0] for d in cursor.description] if cursor.description else []
    return dict(zip(col_names, row, strict=True))


# ---------------------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------------------


@dataclass
class EpisodicMemory:
    """A single episodic memory record — one task execution."""

    id: str
    project_id: str | None
    task_id: str
    task_type: str  # from classify_task_type()
    agent_role: str  # "coo" | "cmo" | "researcher" | "engineer"
    summary: str
    outcome_status: str  # "completed" | "failed" | "escalated"
    feedback: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def from_row(cls, row: dict) -> EpisodicMemory:
        data = dict(row)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "task_type": self.task_type,
            "agent_role": self.agent_role,
            "summary": self.summary,
            "outcome_status": self.outcome_status,
            "feedback": self.feedback,
            "created_at": self.created_at.isoformat(),
        }

    def format(self) -> str:
        """Render as human-readable summary for prompt injection."""
        return (
            f"[{self.agent_role.upper()}] {self.task_type}: {self.summary} "
            f"({self.outcome_status}, {self.created_at.strftime('%Y-%m-%d')})"
        )


# ---------------------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------------------


class EpisodicMemoryStore:
    """CRUD + query for episodic memory in PGLite (async).

    Uses aiosqlite for non-blocking I/O. All public methods are async.

    Schema:
      CREATE TABLE IF NOT EXISTS episodic_memory (
          id              TEXT PRIMARY KEY,
          project_id      TEXT,
          task_id         TEXT NOT NULL,
          task_type       TEXT NOT NULL,
          agent_role      TEXT NOT NULL,
          summary         TEXT NOT NULL,
          outcome_status  TEXT NOT NULL,
          feedback        TEXT,
          created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
      );
      CREATE INDEX IF NOT EXISTS idx_episodic_project ON episodic_memory(project_id);
      CREATE INDEX IF NOT EXISTS idx_episodic_task_type ON episodic_memory(task_type);
      CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic_memory(created_at);
    """

    RETENTION_DAYS = 180

    def __init__(self, db_path: str | None = None, pool_size: int = 5):
        self.db_path = db_path or ":memory:"
        self._pool = AsyncSQLitePool(self.db_path, pool_size=pool_size)
        self._started = False

    async def start(self) -> None:
        """Initialize the connection pool and schema."""
        if self._started:
            return
        self._started = True
        await self._pool.start()
        await self._ensure_schema()

    async def stop(self) -> None:
        """Stop the connection pool."""
        await self._pool.stop()
        self._started = False

    async def _ensure_schema(self) -> None:
        """Create tables and indexes if they don't exist."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS episodic_memory (
                    id              TEXT PRIMARY KEY,
                    project_id      TEXT,
                    task_id         TEXT NOT NULL,
                    task_type       TEXT NOT NULL,
                    agent_role      TEXT NOT NULL,
                    summary         TEXT NOT NULL,
                    outcome_status  TEXT NOT NULL,
                    feedback        TEXT,
                    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_project ON episodic_memory(project_id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_task_type ON episodic_memory(task_type)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic_memory(created_at)"
            )
            await conn.commit()

    async def insert(self, record: EpisodicMemory) -> None:
        """Store a new episodic memory record."""
        await self._pool.execute_write(
            """
            INSERT INTO episodic_memory
                (id, project_id, task_id, task_type, agent_role,
                 summary, outcome_status, feedback, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.project_id,
                record.task_id,
                record.task_type,
                record.agent_role,
                record.summary,
                record.outcome_status,
                record.feedback,
                record.created_at.isoformat(),
            ),
        )

    async def query_by_project(
        self,
        project_id: str | None,
        task_type: str | None = None,
        limit: int = 10,
    ) -> list[EpisodicMemory]:
        """Query episodic memories scoped to a project, optionally filtered by task_type."""
        query = "SELECT * FROM episodic_memory WHERE 1=1"
        params: list[Any] = []

        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        else:
            query += " AND project_id IS NULL"

        if task_type:
            query += " AND task_type = ?"
            params.append(task_type)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = await self._pool.execute(query, tuple(params))
        return [EpisodicMemory.from_row(r) for r in rows]

    async def query_recent(self, days: int = 30, limit: int = 20) -> list[EpisodicMemory]:
        """Fetch episodic memories from the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        rows = await self._pool.execute(
            """
            SELECT * FROM episodic_memory
            WHERE created_at >= ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (cutoff, limit),
        )
        return [EpisodicMemory.from_row(r) for r in rows]

    async def delete_older_than(self, days: int | None = None) -> int:
        """Delete records older than retention window. Returns count deleted."""
        if days is None:
            days = self.RETENTION_DAYS
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        return await self._pool.execute_write(
            "DELETE FROM episodic_memory WHERE created_at < ?",
            (cutoff,),
        )

    async def delete(self, record_id: str) -> int:
        """Delete a single episodic record by id (#53). Returns rowcount.

        Returns 0 when the id was not found -- callers should map that to
        an HTTP 404 in the route layer.
        """
        return await self._pool.execute_write(
            "DELETE FROM episodic_memory WHERE id = ?", (record_id,)
        )

    async def get_task_id(self, record_id: str) -> str | None:
        """Look up the task_id for an episodic record (#53). Returns None
        when the record is missing."""
        row = await self._pool.execute_one(
            "SELECT task_id FROM episodic_memory WHERE id = ?", (record_id,)
        )
        return row["task_id"] if row else None

    async def count_dependent_steps(self, task_id: str) -> int:
        """Count task_step rows that share the given task_id (#53).

        Used by DELETE /api/memories/episodic/{id} to deny deletion when
        dependent execution context still exists, unless ?cascade_steps=true
        is passed.
        """
        row = await self._pool.execute_one(
            "SELECT COUNT(*) as cnt FROM task_step WHERE task_id = ?", (task_id,)
        )
        return int(row["cnt"]) if row else 0

    async def delete_dependent_steps(self, task_id: str) -> int:
        """Cascade-delete task_step rows for a task_id (#53). Returns count."""
        return await self._pool.execute_write(
            "DELETE FROM task_step WHERE task_id = ?", (task_id,)
        )

    async def delete_by_project(self, project_id: str) -> int:
        """Delete all episodic records for a project (GDPR erasure). Returns count deleted."""
        return await self._pool.execute_write(
            "DELETE FROM episodic_memory WHERE project_id = ?",
            (project_id,),
        )
