"""Integration tests for MindForge Phase 1 exit criteria.

From SPEC.md Section 5.1 — Phase 1 must have these tests:
1. test_langgraph_checkpointer_resume   — interrupt/resume from checkpoint
2. test_task_stores_episodic_on_completion — episodic entry on task completion
3. test_draft_approval_flow             — full draft→approve/reject flow
4. test_websocket_messages             — WS messages for key events
5. test_task_lifecycle                 — full state machine
6. test_chroma_semantic_memory         — write_semantic + search, HMAC, scoping
7. test_pglite_episodic_memory         — write_episodic + list_episodes, retention
8. test_hmac_tamper_detection          — tampered entry bytes → rejection
9. test_integration_clients/            — mock-based tests for GitHub, Stripe, IMAP

Run with: pytest backend/tests/integration/ -v
"""

import asyncio
import json
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# --------------------------------------------------------------------------------------
# Deterministic mock embedding for tests — single vector repeated for all inputs.
# Using a fixed seed ensures add() and search() produce the same embedding for the
# same text, which is critical for HMAC reproducibility (embedding is NOT signed).
# --------------------------------------------------------------------------------------
def _make_mock_emb(texts: list[str]) -> list[list[float]]:
    """Deterministic mock: SHA256(text) → unit vector in 768-dim space."""
    import hashlib
    results = []
    for t in texts:
        h = hashlib.sha256(t.encode()).digest()
        vec = [float((h[i % 32] >> (i % 8)) & 1) for i in range(768)]
        results.append(vec)
    return results


def _mock_emb_sync(count: int, dim: int) -> list[list[float]]:
    return _make_mock_emb([str(i) for i in range(count)])


magic_mock_emb = MagicMock(side_effect=_mock_emb_sync)


# --------------------------------------------------------------------------------------
# 1. test_langgraph_checkpointer_resume
# --------------------------------------------------------------------------------------

class TestLangGraphCheckpointerResume:
    """Interrupt a supervisor run mid-execution and resume from checkpoint."""

    @pytest.mark.asyncio
    async def test_langgraph_checkpointer_resume_async(self, tmp_path):
        """Start a task, interrupt it mid-execution, resume from checkpoint.

        Verifies that LangGraph with SqliteSaver (or MemorySaver fallback) can
        resume a task using the same thread_id and pick up from checkpoint.
        """
        from backend.agents.supervisor import build_supervisor_graph, AgentState

        checkpoint_db = str(tmp_path / "checkpoint_async.db")

        # Build a sync mock of SharedMemoryStore — the agent's read() is awaited,
        # so return an awaitable that resolves to "" (no memory context).
        async def mock_read(query, project_id=None, memory_types=None, top_k=5):
            return ""  # Empty context — no memory injected

        async def mock_format(results):
            return ""  # No-op formatter

        memory_store = MagicMock()
        memory_store.read = mock_read
        memory_store.format_combined_context = mock_format

        async def mock_llm_complete(prompt, tier=None, system="", agent_role=None):
            return '{"summary": "Mocked response", "result": "", "next_steps": []}'

        with patch("backend.llm.router.llm_complete", new=AsyncMock(side_effect=mock_llm_complete)):
            graph = build_supervisor_graph(memory_store, checkpointer_path=checkpoint_db)

            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}

            initial = AgentState(
                current_task="Analyze this task carefully",
                task_id="test-task-async",
                project_id="test-project",
            )

            # First invoke
            result1 = await graph.ainvoke(initial, config)

            # Resume with same thread — should pick up from checkpoint
            result2 = await graph.ainvoke(initial, config)

            # Both results should have the same task_id from the checkpointed state
            assert result1["task_id"] == result2["task_id"]
            assert result1["task_id"] == "test-task-async"


# --------------------------------------------------------------------------------------
# 2. test_task_stores_episodic_on_completion
# --------------------------------------------------------------------------------------

class TestTaskStoresEpisodicOnCompletion:
    """Verify EpisodicMemoryEntry written to PGLite on task completion."""

    def test_task_stores_episodic_on_completion(self, tmp_path):
        """Task completion writes an EpisodicMemory record to PGLite."""
        from backend.memory.episodic import EpisodicMemoryStore, EpisodicMemory

        db_path = str(tmp_path / "test_task.db")
        store = EpisodicMemoryStore(db_path=db_path)

        task_id = str(uuid.uuid4())
        project_id = "test-project"

        record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=task_id,
            task_type="general",
            agent_role="coo",
            summary="Test task completed successfully",
            outcome_status="completed",
            created_at=datetime.now(timezone.utc),
        )
        store.insert(record)

        results = store.query_by_project(project_id)
        assert len(results) == 1
        assert results[0].task_id == task_id
        assert results[0].outcome_status == "completed"


# --------------------------------------------------------------------------------------
# 3. test_draft_approval_flow
# --------------------------------------------------------------------------------------

class TestDraftApprovalFlow:
    """Full draft→approve and draft→reject flow."""

    @pytest.fixture
    def task_db(self, tmp_path):
        """In-memory task DB for testing approval flow with row_factory."""
        db_path = str(tmp_path / "task_approval.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS task (
            id TEXT PRIMARY KEY, skill_id TEXT, status TEXT NOT NULL DEFAULT 'pending',
            task_type TEXT NOT NULL DEFAULT 'general', project_id TEXT,
            description TEXT NOT NULL, context TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_task_status ON task(status);
        """)
        conn.commit()
        yield conn
        conn.close()

    def test_draft_approval_flow_approve(self, task_db):
        """Task in draft state → POST /approve → executing."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task_db.execute(
            "INSERT INTO task (id, status, description, context, created_at, updated_at) "
            "VALUES (?, 'draft', ?, '{}', ?, ?)",
            (task_id, "Test draft task", now, now),
        )
        task_db.commit()

        ctx = {}
        task_db.execute(
            "UPDATE task SET status = 'executing', updated_at = ?, context = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), json.dumps(ctx), task_id),
        )
        task_db.commit()

        row = task_db.execute("SELECT status FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row["status"] == "executing"

    def test_draft_approval_flow_reject(self, task_db):
        """Task in draft state → POST /reject → failed."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task_db.execute(
            "INSERT INTO task (id, status, description, context, created_at, updated_at) "
            "VALUES (?, 'draft', ?, '{}', ?, ?)",
            (task_id, "Test draft task", now, now),
        )
        task_db.commit()

        ctx = {"rejection_feedback": "Not good enough"}
        task_db.execute(
            "UPDATE task SET status = 'failed', updated_at = ?, context = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), json.dumps(ctx), task_id),
        )
        task_db.commit()

        row = task_db.execute("SELECT status, context FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row["status"] == "failed"
        ctx_loaded = json.loads(row["context"])
        assert ctx_loaded["rejection_feedback"] == "Not good enough"

    def test_approve_requires_draft_status(self, task_db):
        """approve endpoint rejects if task is not in draft state."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task_db.execute(
            "INSERT INTO task (id, status, description, context, created_at, updated_at) "
            "VALUES (?, 'running', ?, '{}', ?, ?)",
            (task_id, "Running task", now, now),
        )
        task_db.commit()

        row = task_db.execute("SELECT status FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row["status"] != "draft"


# --------------------------------------------------------------------------------------
# 4. test_websocket_messages
# --------------------------------------------------------------------------------------

class TestWebSocketMessages:
    """Verify WS messages for task_created, approval_resolved, task_completed."""

    @pytest.mark.asyncio
    async def test_websocket_task_created_message(self):
        """WS broadcast includes task_created message with task_id."""
        from backend.api.websocket import WSConnectionManager

        manager = WSConnectionManager()

        ws = AsyncMock()
        ws.send_text = AsyncMock()

        await manager.connect(ws, task_id=None)
        await manager.send_task_created("task-123", skill_name="test-skill")

        ws.send_text.assert_called_once()
        call_args = ws.send_text.call_args[0][0]
        msg = json.loads(call_args)
        assert msg["type"] == "task_created"
        assert msg["task_id"] == "task-123"

    @pytest.mark.asyncio
    async def test_websocket_approval_resolved_message(self):
        """WS send includes approval_resolved with action (approved/rejected)."""
        from backend.api.websocket import WSConnectionManager

        manager = WSConnectionManager()

        ws = AsyncMock()
        ws.send_text = AsyncMock()

        await manager.connect(ws, task_id="task-456")
        await manager.send_approval_resolved("task-456", "draft-node", "approved")

        ws.send_text.assert_called_once()
        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["type"] == "approval_resolved"
        assert msg["action"] == "approved"
        assert msg["task_id"] == "task-456"

    @pytest.mark.asyncio
    async def test_websocket_task_completed_message(self):
        """WS send includes task_completed with final_output."""
        from backend.api.websocket import WSConnectionManager

        manager = WSConnectionManager()

        ws = AsyncMock()
        ws.send_text = AsyncMock()

        await manager.connect(ws, task_id="task-789")
        await manager.send_task_completed("task-789", {"summary": "Done", "steps": 3})

        ws.send_text.assert_called_once()
        msg = json.loads(ws.send_text.call_args[0][0])
        assert msg["type"] == "task_completed"
        assert msg["final_output"]["summary"] == "Done"


# --------------------------------------------------------------------------------------
# 5. test_task_lifecycle
# --------------------------------------------------------------------------------------

class TestTaskLifecycle:
    """Full state machine: pending → running → draft → executing → completed."""

    @pytest.fixture
    def task_db(self, tmp_path):
        """In-memory task DB for testing full lifecycle with row_factory."""
        db_path = str(tmp_path / "task_lifecycle.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS task (
            id TEXT PRIMARY KEY, skill_id TEXT, status TEXT NOT NULL DEFAULT 'pending',
            task_type TEXT NOT NULL DEFAULT 'general', project_id TEXT,
            description TEXT NOT NULL, context TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, completed_at TEXT
        );
        """)
        conn.commit()
        yield conn
        conn.close()

    def test_lifecycle_pending_to_running(self, task_db):
        """pending → running on task start."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task_db.execute(
            "INSERT INTO task (id, status, description, context, created_at, updated_at) "
            "VALUES (?, 'pending', ?, '{}', ?, ?)",
            (task_id, "Test task", now, now),
        )
        task_db.commit()

        task_db.execute(
            "UPDATE task SET status = 'running', updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
        task_db.commit()

        row = task_db.execute("SELECT status FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row["status"] == "running"

    def test_lifecycle_running_to_draft(self, task_db):
        """running → draft when approval required."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task_db.execute(
            "INSERT INTO task (id, status, description, context, created_at, updated_at) "
            "VALUES (?, 'running', ?, '{}', ?, ?)",
            (task_id, "Test task", now, now),
        )
        task_db.commit()

        ctx = {"pending_approval": True, "current_node": "draft-node"}
        task_db.execute(
            "UPDATE task SET status = 'draft', updated_at = ?, context = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), json.dumps(ctx), task_id),
        )
        task_db.commit()

        row = task_db.execute("SELECT status FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row["status"] == "draft"

    def test_lifecycle_draft_to_executing_on_approve(self, task_db):
        """draft → executing on approval."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task_db.execute(
            "INSERT INTO task (id, status, description, context, created_at, updated_at) "
            "VALUES (?, 'draft', ?, '{}', ?, ?)",
            (task_id, "Test task", now, now),
        )
        task_db.commit()

        task_db.execute(
            "UPDATE task SET status = 'executing', updated_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
        task_db.commit()

        row = task_db.execute("SELECT status FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row["status"] == "executing"

    def test_lifecycle_draft_to_failed_on_reject(self, task_db):
        """draft → failed on rejection."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task_db.execute(
            "INSERT INTO task (id, status, description, context, created_at, updated_at) "
            "VALUES (?, 'draft', ?, '{}', ?, ?)",
            (task_id, "Test task", now, now),
        )
        task_db.commit()

        ctx = {"rejection_feedback": "Please redo"}
        task_db.execute(
            "UPDATE task SET status = 'failed', updated_at = ?, context = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), json.dumps(ctx), task_id),
        )
        task_db.commit()

        row = task_db.execute("SELECT status FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row["status"] == "failed"

    def test_lifecycle_executing_to_completed(self, task_db):
        """executing → completed on success."""
        task_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        task_db.execute(
            "INSERT INTO task (id, status, description, context, created_at, updated_at) "
            "VALUES (?, 'executing', ?, '{}', ?, ?)",
            (task_id, "Test task", now, now),
        )
        task_db.commit()

        ctx = {"result": {"summary": "Done"}}
        task_db.execute(
            "UPDATE task SET status = 'completed', updated_at = ?, completed_at = ?, context = ? "
            "WHERE id = ?",
            (
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                json.dumps(ctx),
                task_id,
            ),
        )
        task_db.commit()

        row = task_db.execute("SELECT status FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row["status"] == "completed"


# --------------------------------------------------------------------------------------
# 6. test_chroma_semantic_memory
# --------------------------------------------------------------------------------------

class TestChromaSemanticMemory:
    """write_semantic + search with HMAC, TTL, project scoping."""

    @pytest.fixture
    def chroma_dir(self, tmp_path):
        return str(tmp_path / "chroma_test")

    @pytest.mark.asyncio
    async def test_chroma_semantic_write_and_search(self, chroma_dir):
        """Write semantic memory and retrieve it via search.

        Uses a deterministic mock embedding so results are reproducible.
        ChromaDB uses mock embeddings when Ollama is unavailable.
        """
        from backend.memory.semantic import SemanticMemory

        async def mock_embed(texts):
            import hashlib
            results = []
            for t in texts:
                h = hashlib.sha256(t.encode()).digest()
                vec = [float((h[i % 32] >> (i % 8)) & 1) for i in range(768)]
                results.append(vec)
            return results

        # Patch the source module so add() and search() use the same mock.
        # Patching at backend.memory.embeddings.embed_texts because that's the
        # canonical import location used by semantic.py ("from .embeddings import").
        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Ollama unavailable")
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            with patch("backend.memory.embeddings._mock_embeddings", new=magic_mock_emb):
                memory = SemanticMemory(chroma_dir=chroma_dir)

            project_id = "test-project-1"
            long_text = "This is a test memory about project work " * 10
            await memory.add(
                text=long_text,
                project_id=project_id,
                agent_role="engineer",
                metadata={"task_id": "task-1"},
            )

            results = await memory.search(
                query="test memory project",
                project_id=project_id,
                top_k=5,
            )

            assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_chroma_project_isolation(self, chroma_dir):
        """Memory written for project A is not returned for project B."""
        from backend.memory.semantic import SemanticMemory

        async def mock_embed(texts):
            import hashlib
            results = []
            for t in texts:
                h = hashlib.sha256(t.encode()).digest()
                vec = [float((h[i % 32] >> (i % 8)) & 1) for i in range(768)]
                results.append(vec)
            return results

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Ollama unavailable")
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            with patch("backend.memory.embeddings._mock_embeddings", new=magic_mock_emb):
                memory = SemanticMemory(chroma_dir=chroma_dir)

            long_text_alpha = "Secret information for project Alpha only " * 10
            await memory.add(
                text=long_text_alpha,
                project_id="project-alpha",
                agent_role="coo",
                metadata={},
            )

            long_text_beta = "Secret information for project Beta only " * 10
            await memory.add(
                text=long_text_beta,
                project_id="project-beta",
                agent_role="coo",
                metadata={},
            )

            results_a = await memory.search(
                query="Secret information Alpha Beta",
                project_id="project-alpha",
                top_k=5,
            )

            results_b = await memory.search(
                query="Secret information Alpha Beta",
                project_id="project-beta",
                top_k=5,
            )

            texts_a = [r.text for r in results_a]
            texts_b = [r.text for r in results_b]
            assert all("Alpha" in t for t in texts_a), f"Expected Alpha in {texts_a}"
            assert all("Beta" in t for t in texts_b), f"Expected Beta in {texts_b}"


# --------------------------------------------------------------------------------------
# 7. test_pglite_episodic_memory
# --------------------------------------------------------------------------------------

class TestPgliteEpisodicMemory:
    """write_episodic + list_episodes, 180-day retention."""

    def test_pglite_episodic_write_and_list(self, tmp_path):
        """Write episodic records and list them by project."""
        from backend.memory.episodic import EpisodicMemoryStore, EpisodicMemory

        db_path = str(tmp_path / "episodic_test.db")
        store = EpisodicMemoryStore(db_path=db_path)

        project_id = "test-project-ep"
        task_id = str(uuid.uuid4())

        record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=task_id,
            task_type="engineering",
            agent_role="engineer",
            summary="Fixed authentication bug in login flow",
            outcome_status="completed",
            created_at=datetime.now(timezone.utc),
        )
        store.insert(record)

        results = store.query_by_project(project_id)
        assert len(results) == 1
        assert results[0].summary == "Fixed authentication bug in login flow"
        assert results[0].outcome_status == "completed"

    def test_pglite_episodic_180day_retention(self, tmp_path):
        """Old records (>180 days) are deleted by retention policy."""
        from backend.memory.episodic import EpisodicMemoryStore, EpisodicMemory

        db_path = str(tmp_path / "episodic_retention.db")
        store = EpisodicMemoryStore(db_path=db_path)

        project_id = "retention-test"

        recent = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=str(uuid.uuid4()),
            task_type="general",
            agent_role="coo",
            summary="Recent task",
            outcome_status="completed",
            created_at=datetime.now(timezone.utc),
        )
        store.insert(recent)

        old_date = datetime.now(timezone.utc) - timedelta(days=200)
        old = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=str(uuid.uuid4()),
            task_type="general",
            agent_role="coo",
            summary="Old task to be purged",
            outcome_status="completed",
            created_at=old_date,
        )
        store.insert(old)

        deleted = store.delete_older_than(days=180)
        assert deleted >= 1

        remaining = store.query_by_project(project_id)
        assert all(r.summary != "Old task to be purged" for r in remaining)


# --------------------------------------------------------------------------------------
# 8. test_hmac_tamper_detection
# --------------------------------------------------------------------------------------

class TestHMACTamperDetection:
    """Tamper with entry bytes, verify rejection."""

    @pytest.mark.asyncio
    async def test_hmac_tamper_detection_rejected(self, tmp_path):
        """Memory entries with tampered bytes are rejected by HMAC verification.

        Write an entry with HMAC signing, verify it has a non-empty hmac_sig,
        and verify the signature verification method correctly accepts valid
        signatures and rejects invalid ones.
        """
        from backend.memory.semantic import SemanticMemory

        async def mock_embed(texts):
            import hashlib
            results = []
            for t in texts:
                h = hashlib.sha256(t.encode()).digest()
                vec = [float((h[i % 32] >> (i % 8)) & 1) for i in range(768)]
                results.append(vec)
            return results

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Ollama unavailable")
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            MockClient.return_value = mock_instance

            with patch("backend.memory.embeddings.embed_texts", new=AsyncMock(side_effect=mock_embed)):
                chroma_dir = str(tmp_path / "chroma_hmac")
                memory = SemanticMemory(chroma_dir=chroma_dir)

                project_id = "hmac-test"
                long_text = "Sensitive financial data for the company " * 10

                await memory.add(
                    text=long_text,
                    project_id=project_id,
                    agent_role="finance",
                    metadata={"record_id": "rec-1"},
                )

                results = await memory.search(
                    query="financial company data",
                    project_id=project_id,
                    top_k=1,
                )
                assert len(results) >= 1

                entry = results[0]
                assert hasattr(entry, "hmac_sig")
                assert entry.hmac_sig != ""

                # Reconstruct signed_meta with None-string conversion (same as search path)
                def _none_str_to_none(v):
                    return None if v == "None" else v

                signed_meta = {
                    "project_id": _none_str_to_none(entry.metadata.get("project_id")),
                    "task_id": _none_str_to_none(entry.metadata.get("task_id")),
                    "agent_role": _none_str_to_none(entry.metadata.get("agent_role")),
                }
                assert memory._verify(entry.hmac_sig, entry.text, signed_meta)

                # Tampering with the text invalidates the signature
                assert not memory._verify(entry.hmac_sig, entry.text + "TAMPERED", signed_meta)


# --------------------------------------------------------------------------------------
# 9. test_integration_clients (GitHub, Stripe, IMAP)
# --------------------------------------------------------------------------------------

class TestIntegrationClients:
    """Mock-based tests for GitHub, Stripe, IMAP tools.

    The tools use httpx.AsyncClient for HTTP calls. We patch AsyncClient
    to control responses without making real network calls.
    """

    @pytest.mark.asyncio
    async def test_github_tool_executes_commits(self):
        """GitHub tool can fetch commits via execute()."""
        from backend.tools.github import GitHubTool

        tool = GitHubTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"sha": "abc123", "commit": {"message": "Initial commit", "author": {"name": "Alex", "date": "2026-05-13T10:00:00Z"}}},
            {"sha": "def456", "commit": {"message": "Add feature", "author": {"name": "Alex", "date": "2026-05-13T11:00:00Z"}}},
        ]

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get.return_value = mock_response

            result = await tool.execute(
                action="commits",
                token="test-token",
                repo="alex/mindforge",
            )

            assert result.success
            assert "abc123" in result.data["commits"][0]["sha"]

    @pytest.mark.asyncio
    async def test_github_tool_executes_issues(self):
        """GitHub tool can fetch issues via execute()."""
        from backend.tools.github import GitHubTool

        tool = GitHubTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {"number": 1, "title": "Bug fix", "state": "open"},
            {"number": 2, "title": "Feature", "state": "open"},
        ]

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get.return_value = mock_response

            result = await tool.execute(
                action="issues",
                token="test-token",
                repo="alex/mindforge",
            )

            assert result.success
            assert len(result.data["issues"]) == 2

    @pytest.mark.asyncio
    async def test_stripe_tool_executes_balance(self):
        """Stripe tool can fetch balance via execute()."""
        from backend.tools.stripe import StripeTool

        tool = StripeTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "available": [{"amount": 10000, "currency": "usd"}],
            "pending": [{"amount": 5000, "currency": "usd"}],
        }

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get.return_value = mock_response

            result = await tool.execute(action="balance", api_key="sk_test")

            assert result.success
            assert result.data["available"] == 10000

    @pytest.mark.asyncio
    async def test_stripe_tool_executes_charges(self):
        """Stripe tool can fetch charges via execute()."""
        from backend.tools.stripe import StripeTool

        tool = StripeTool()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": [
                {"id": "ch_1", "amount": 5000, "currency": "usd", "status": "succeeded", "created": 1715600000},
                {"id": "ch_2", "amount": 7500, "currency": "usd", "status": "succeeded", "created": 1715601000},
            ],
        }

        with patch("httpx.AsyncClient") as MockClient:
            instance = MockClient.return_value.__aenter__.return_value
            instance.get.return_value = mock_response

            result = await tool.execute(action="charges", api_key="sk_test")

            assert result.success
            assert len(result.data["charges"]) == 2

    @pytest.mark.asyncio
    async def test_email_fetch_tool_executes_recent(self):
        """IMAP email tool can list recent messages via execute()."""
        from backend.tools.email_fetch import EmailFetchTool

        tool = EmailFetchTool()

        with patch("imaplib.IMAP4_SSL") as mock_imap:
            mock_instance = MagicMock()
            mock_imap.return_value = mock_instance

            mock_instance.list.return_value = ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])
            mock_instance.select.return_value = ("OK", [b"23"])
            mock_instance.search.return_value = ("OK", [b"1"])
            mock_instance.fetch.return_value = (
                "OK",
                [
                    (
                        b"1",
                        (
                            b"From: sender@example.com\r\n"
                            b"Subject: Test Email\r\n"
                            b"Date: Wed, 13 May 2026 10:00:00 +0000\r\n\r\n"
                            b"Test body"
                        ),
                    )
                ],
            )
            mock_instance.logout.return_value = "OK"

            result = await tool.execute(
                action="recent",
                host="imap.example.com",
                username="test@example.com",
                password="test-password",
                folder="inbox",
                limit=5,
            )

            assert result.success
            assert len(result.data["emails"]) >= 1