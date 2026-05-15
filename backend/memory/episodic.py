"""Episodic memory — structured task history stored in PGLite.

From SPEC.md §2.2 and §5.7.
Stores completed task records enabling "what did we do last week?" queries.
180-day rolling retention window.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

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
    def from_row(cls, row: sqlite3.Row) -> EpisodicMemory:
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
    """CRUD + query for episodic memory in PGLite.

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

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or ":memory:"
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
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
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_project ON episodic_memory(project_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_task_type ON episodic_memory(task_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_episodic_created ON episodic_memory(created_at)"
            )
            conn.commit()

    def insert(self, record: EpisodicMemory) -> None:
        """Store a new episodic memory record."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
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
            conn.commit()

    def query_by_project(
        self,
        project_id: str | None,
        task_type: str | None = None,
        limit: int = 10,
    ) -> list[EpisodicMemory]:
        """Query episodic memories scoped to a project, optionally filtered by task_type."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
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

            rows = conn.execute(query, params).fetchall()
            return [EpisodicMemory.from_row(r) for r in rows]

    def query_recent(self, days: int = 30, limit: int = 20) -> list[EpisodicMemory]:
        """Fetch episodic memories from the last N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM episodic_memory
                WHERE created_at >= ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (cutoff, limit),
            ).fetchall()
            return [EpisodicMemory.from_row(r) for r in rows]

    def delete_older_than(self, days: int | None = None) -> int:
        """Delete records older than retention window. Returns count deleted."""
        if days is None:
            days = self.RETENTION_DAYS
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM episodic_memory WHERE created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount

    def delete(self, record_id: str) -> int:
        """Delete a single episodic record by id (#53). Returns rowcount.

        Returns 0 when the id was not found -- callers should map that to
        an HTTP 404 in the route layer.
        """
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM episodic_memory WHERE id = ?", (record_id,)
            )
            conn.commit()
            return cur.rowcount

    def get_task_id(self, record_id: str) -> str | None:
        """Look up the task_id for an episodic record (#53). Returns None
        when the record is missing."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT task_id FROM episodic_memory WHERE id = ?", (record_id,)
            ).fetchone()
            return row[0] if row else None

    def count_dependent_steps(self, task_id: str) -> int:
        """Count task_step rows that share the given task_id (#53).

        Used by DELETE /api/memories/episodic/{id} to deny deletion when
        dependent execution context still exists, unless ?cascade_steps=true
        is passed.
        """
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM task_step WHERE task_id = ?", (task_id,)
            ).fetchone()
            return int(row[0]) if row else 0

    def delete_dependent_steps(self, task_id: str) -> int:
        """Cascade-delete task_step rows for a task_id (#53). Returns count."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM task_step WHERE task_id = ?", (task_id,)
            )
            conn.commit()
            return cur.rowcount

    def delete_by_project(self, project_id: str) -> int:
        """Delete all episodic records for a project (GDPR erasure). Returns count deleted."""
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                "DELETE FROM episodic_memory WHERE project_id = ?",
                (project_id,),
            )
            conn.commit()
            return cur.rowcount
