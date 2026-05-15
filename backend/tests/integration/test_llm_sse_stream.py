"""Integration tests for GET /api/tasks/{task_id}/stream (#50).

The route exposes ``llm_complete_stream`` over Server-Sent Events so the
dashboard can render incremental drafts. Pin:

  - SSE content-type ``text/event-stream``.
  - Tokens flow as ``data:`` events; final sentinel ``data: [DONE]``.
  - Unknown task -> 404 (no streaming generator created).
  - Generator is closed on client disconnect (no leaked tasks /
    upstream LLM calls).
  - The route reads from the configured streaming wrapper, NOT directly
    from the OpenRouter client -- so the tests can patch one symbol.
"""

from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile
from collections.abc import AsyncGenerator, Iterator

# Pre-import patches mirror the other integration tests.
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

_TASK_DDL = """
CREATE TABLE IF NOT EXISTS tasks (
    id            TEXT PRIMARY KEY,
    skill_id      TEXT,
    skill_version INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL DEFAULT 'pending',
    task_type     TEXT NOT NULL DEFAULT 'general',
    project_id    TEXT,
    description   TEXT NOT NULL,
    context       TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at  TEXT
);
"""


def _seed_task(db_path: str, task_id: str, description: str = "draft me a reply") -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO tasks (id, description) VALUES (?, ?)",
        (task_id, description),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def db_path() -> Iterator[str]:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)  # noqa: SIM115
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.executescript(_TASK_DDL)
    conn.commit()
    conn.close()
    try:
        yield tmp.name
    finally:
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Fake streamer used by every test -- patched into the route via
# monkeypatch so we never make a real LLM call.
# ---------------------------------------------------------------------------


_FAKE_TOKENS = ["Hello", " ", "world", "!"]
_close_calls: list[str] = []


async def _fake_token_stream(*args, **kwargs) -> AsyncGenerator[str, None]:
    """Emit four tokens. Records when the consumer closes early."""
    try:
        for token in _FAKE_TOKENS:
            yield token
    finally:
        # Recorded so test_disconnect_closes_generator can assert on it
        _close_calls.append("closed")


@pytest.fixture
def client(db_path, monkeypatch) -> Iterator[TestClient]:
    """Mount only the tasks router with the SSE route under test."""
    from backend.api.deps import db_dep
    from backend.api.routes import tasks as tasks_routes

    # Patch the streaming entry point the route uses. The route MUST call
    # backend.api.routes.tasks.llm_complete_stream (a module-level alias)
    # so this patch swaps in our fake without monkey-patching the LLM
    # router internals.
    monkeypatch.setattr(
        tasks_routes, "llm_complete_stream", _fake_token_stream, raising=False
    )

    app = FastAPI()
    app.include_router(tasks_routes.router)

    def _override_db_dep() -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[db_dep] = _override_db_dep
    _close_calls.clear()
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSSEHappyPath:
    def test_unknown_task_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/tasks/does-not-exist/stream")
        assert resp.status_code == 404
        # Nothing should have been streamed
        assert "[DONE]" not in resp.text

    def test_known_task_returns_event_stream_content_type(
        self, client: TestClient, db_path: str
    ) -> None:
        _seed_task(db_path, "t-abc")
        with client.stream("GET", "/api/tasks/t-abc/stream") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            # Drain so the connection closes cleanly
            for _ in resp.iter_text():
                pass

    def test_tokens_arrive_as_sse_data_events(
        self, client: TestClient, db_path: str
    ) -> None:
        _seed_task(db_path, "t-abc")
        with client.stream("GET", "/api/tasks/t-abc/stream") as resp:
            assert resp.status_code == 200
            body = "".join(resp.iter_text())
        # Each token is delivered as a `data:` SSE event
        for token in _FAKE_TOKENS:
            assert token in body
        # Final sentinel signals end-of-stream
        assert "[DONE]" in body
        # Lines are SSE-shaped (data: prefix + blank-line terminator)
        assert body.count("data:") >= len(_FAKE_TOKENS)


# ---------------------------------------------------------------------------
# Cleanup -- disconnect must close the upstream generator
# ---------------------------------------------------------------------------


class TestDisconnectCleanup:
    def test_disconnect_closes_generator(
        self, client: TestClient, db_path: str
    ) -> None:
        """Even if the consumer abandons the stream early, the generator
        must run its finally block (the source of any LLM call cleanup)."""
        _seed_task(db_path, "t-cancel")
        with client.stream("GET", "/api/tasks/t-cancel/stream") as resp:
            assert resp.status_code == 200
            # Read just one chunk, then walk away.
            for _ in resp.iter_bytes():
                break
        # `_fake_token_stream`'s finally block appends "closed" exactly
        # once when the generator is GC'd / aclose()d.
        assert _close_calls == ["closed"], (
            f"expected exactly one 'closed' event, got {_close_calls!r}"
        )


# ---------------------------------------------------------------------------
# Sentinel formatting -- pin the protocol so a future refactor doesn't
# silently change it.
# ---------------------------------------------------------------------------


def test_sse_done_sentinel_is_last_data_event(client: TestClient, db_path: str) -> None:
    _seed_task(db_path, "t-end")
    with client.stream("GET", "/api/tasks/t-end/stream") as resp:
        body = "".join(resp.iter_text())
    data_lines = [
        line for line in body.splitlines() if line.startswith("data:")
    ]
    assert data_lines, body
    assert data_lines[-1].strip() == "data: [DONE]"
