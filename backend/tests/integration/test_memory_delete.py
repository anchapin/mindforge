"""Integration tests for per-record memory deletion endpoints (#53).

Pin the contract:
  - DELETE /api/memories/semantic/{id}   -> drops one ChromaDB record
  - DELETE /api/memories/episodic/{id}   -> drops one PGLite row, denies
    with 409 when dependent task_step rows exist (unless ?cascade_steps=true)
  - DELETE /api/memories/style           -> resets writing profile to defaults
  - 404 on unknown ids in all three.

ChromaDB and PGLite are stubbed so the tests run inside the unit-test loop
without docker compose; the real implementations call .delete() on the
underlying objects -- exercised by the existing integration tests.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator

# Pre-import patches mirror the other integration tests
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

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ---------------------------------------------------------------------------
# DB scaffold -- minimal episodic_memory + task_step + writing_profile
# ---------------------------------------------------------------------------


_DDL = """
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
CREATE TABLE IF NOT EXISTS task_step (
    id                       TEXT PRIMARY KEY,
    task_id                  TEXT NOT NULL,
    node_id                  TEXT NOT NULL,
    agent_role               TEXT NOT NULL,
    step_order               INTEGER NOT NULL DEFAULT 0,
    status                   TEXT NOT NULL DEFAULT 'pending'
);
CREATE TABLE IF NOT EXISTS writing_profile (
    id                  TEXT PRIMARY KEY,
    tone                TEXT NOT NULL DEFAULT 'semi-formal',
    sentence_length     TEXT NOT NULL DEFAULT 'medium',
    first_person        TEXT NOT NULL DEFAULT 'I',
    signature_phrases   TEXT NOT NULL DEFAULT '[]',
    greeting_style      TEXT NOT NULL DEFAULT 'Hi [Name],',
    signoff_style       TEXT NOT NULL DEFAULT 'Cheers',
    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _seed_episodic(db_path: str, episodic_id: str, task_id: str = "task-1") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO episodic_memory (id, project_id, task_id, task_type, "
        "agent_role, summary, outcome_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (episodic_id, "p1", task_id, "skill", "cmo", "drafted", "completed"),
    )
    conn.commit()
    conn.close()


def _seed_step(db_path: str, task_id: str, node_id: str = "draft") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO task_step (id, task_id, node_id, agent_role) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), task_id, node_id, "cmo"),
    )
    conn.commit()
    conn.close()


def _seed_profile(db_path: str, **fields) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO writing_profile (id, tone, sentence_length, signoff_style) "
        "VALUES ('default', ?, ?, ?)",
        (
            fields.get("tone", "playful"),
            fields.get("sentence_length", "long"),
            fields.get("signoff_style", "Ciao"),
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Stub SharedMemoryStore -- we only wire the three sub-stores the deletion
# routes touch. The full SharedMemoryStore surface is exercised elsewhere.
# ---------------------------------------------------------------------------


class _StubSemantic:
    def __init__(self):
        self._records: dict[str, dict] = {}
        self.deleted_ids: list[str] = []

    def add(self, record_id: str, text: str = "x") -> None:
        self._records[record_id] = {"text": text}

    def count(self, project_id=None) -> int:  # noqa: ARG002
        return len(self._records)

    def delete(self, record_ids):
        if isinstance(record_ids, str):
            record_ids = [record_ids]
        for rid in record_ids:
            if rid in self._records:
                del self._records[rid]
                self.deleted_ids.append(rid)

    def has(self, record_id: str) -> bool:
        return record_id in self._records


class _StubStore:
    """Just enough surface for the deletion routes."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._semantic = _StubSemantic()
        # Late import so the test module loads even when the real stores
        # would fail (no chroma, no /app dir, etc.).
        from backend.memory.episodic import EpisodicMemoryStore
        from backend.memory.style import WritingProfileStore

        self._episodic = EpisodicMemoryStore(db_path=db_path)
        self._style = WritingProfileStore(db_path=db_path)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path() -> Iterator[str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(_DDL)
    conn.commit()
    conn.close()
    try:
        yield tmp.name
    finally:
        os.unlink(tmp.name)


@pytest.fixture
def store(db_path) -> _StubStore:
    return _StubStore(db_path)


@pytest.fixture
def client(store, db_path) -> Iterator[TestClient]:
    from backend.api.deps import db_dep, memory_dep
    from backend.api.routes import memories as memories_routes

    app = FastAPI()
    app.include_router(memories_routes.router)

    async def _override_memory_dep():
        return store

    def _override_db_dep() -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[memory_dep] = _override_memory_dep
    app.dependency_overrides[db_dep] = _override_db_dep
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Semantic deletion
# ---------------------------------------------------------------------------


class TestSemanticDelete:
    def test_delete_unknown_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/api/memories/semantic/nope")
        assert resp.status_code == 404

    def test_delete_known_drops_record_and_returns_count(
        self, client: TestClient, store: _StubStore
    ) -> None:
        store._semantic.add("rec-1")
        store._semantic.add("rec-2")
        assert store._semantic.count() == 2

        resp = client.delete("/api/memories/semantic/rec-1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["deleted"] is True
        assert body["id"] == "rec-1"
        # ChromaDB count drops
        assert body["count_after"] == 1
        assert store._semantic.count() == 1
        # And the underlying delete was actually called
        assert store._semantic.deleted_ids == ["rec-1"]


# ---------------------------------------------------------------------------
# Episodic deletion -- with task_step dependency handling
# ---------------------------------------------------------------------------


class TestEpisodicDelete:
    def test_delete_unknown_returns_404(self, client: TestClient) -> None:
        resp = client.delete("/api/memories/episodic/nope")
        assert resp.status_code == 404

    def test_delete_with_no_dependents_succeeds(
        self, client: TestClient, db_path: str
    ) -> None:
        _seed_episodic(db_path, "ep-1", task_id="task-isolated")
        resp = client.delete("/api/memories/episodic/ep-1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["deleted"] is True
        assert body["id"] == "ep-1"
        # Row really gone
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT id FROM episodic_memory WHERE id = ?", ("ep-1",)
            ).fetchone()
        finally:
            conn.close()
        assert row is None

    def test_delete_with_dependent_steps_returns_409(
        self, client: TestClient, db_path: str
    ) -> None:
        _seed_episodic(db_path, "ep-2", task_id="task-with-steps")
        _seed_step(db_path, task_id="task-with-steps")
        _seed_step(db_path, task_id="task-with-steps")

        resp = client.delete("/api/memories/episodic/ep-2")
        assert resp.status_code == 409, resp.text
        # Detail must surface the count so the user can see the blocker
        detail = resp.json()["detail"]
        assert "2" in detail or "task_step" in detail
        # Episodic row still present (deny was atomic)
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT id FROM episodic_memory WHERE id = ?", ("ep-2",)
            ).fetchone()
        finally:
            conn.close()
        assert row is not None

    def test_cascade_steps_query_param_overrides_409(
        self, client: TestClient, db_path: str
    ) -> None:
        _seed_episodic(db_path, "ep-3", task_id="task-cascade")
        _seed_step(db_path, task_id="task-cascade")
        _seed_step(db_path, task_id="task-cascade")

        resp = client.delete("/api/memories/episodic/ep-3?cascade_steps=true")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["deleted"] is True
        assert body["cascaded_steps"] == 2
        # Both episodic and step rows are gone
        conn = sqlite3.connect(db_path)
        try:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM episodic_memory WHERE id = ?", ("ep-3",)
                ).fetchone()[0]
                == 0
            )
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM task_step WHERE task_id = ?", ("task-cascade",)
                ).fetchone()[0]
                == 0
            )
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Style reset
# ---------------------------------------------------------------------------


class TestStyleReset:
    def test_reset_overrides_custom_values_with_defaults(
        self, client: TestClient, db_path: str, store: _StubStore
    ) -> None:
        # Seed a customized profile
        _seed_profile(db_path, tone="playful", sentence_length="long", signoff_style="Ciao")
        before = store._style.get().to_dict()
        assert before["tone"] == "playful"
        assert before["signoff_style"] == "Ciao"

        resp = client.delete("/api/memories/style")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["reset"] is True
        # GET /style should now return the spec defaults
        defaults = store._style.get().to_dict()
        assert defaults["tone"] == "semi-formal"
        assert defaults["sentence_length"] == "medium"
        assert defaults["first_person"] == "I"
        assert defaults["greeting_style"] == "Hi [Name],"
        assert defaults["signoff_style"] == "Cheers"
        assert defaults["signature_phrases"] == []

    def test_reset_is_idempotent(self, client: TestClient) -> None:
        # Calling reset twice in a row must not raise (no row vs row exists)
        r1 = client.delete("/api/memories/style")
        r2 = client.delete("/api/memories/style")
        assert r1.status_code == 200
        assert r2.status_code == 200
