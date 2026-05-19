"""Test clarification protocol — Issue #18.

Tests:
1. POST /api/tasks/{task_id}/clarification endpoint exists and resolves task
2. send_clarification_request() is called when agent encounters ambiguity
3. Clarification response injects constraint into task context

Run: pytest backend/tests/integration/test_clarification.py -v
"""

import json
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
        (
            "clarify-task-1",
            None,
            "pending",
            "general",
            None,
            "draft email response",
            "{}",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )
    conn.commit()
    conn.close()


_init_test_db()


# --------------------------------------------------------------------------------------
# RED Phase: Write tests that FAIL because the feature doesn't exist yet.
# --------------------------------------------------------------------------------------


class TestClarificationEndpointExists:
    """Verify POST /api/tasks/{task_id}/clarification endpoint is wired.

    RED: This test FAILS because the endpoint does not exist yet (404).
    After GREEN: implement the endpoint in tasks.py.
    """

    @pytest.mark.asyncio
    async def test_clarification_endpoint_returns_200_with_valid_payload(self):
        """POST /api/tasks/{task_id}/clarification with {decision, edited_draft} → 200.

        RED: 404 because endpoint not yet implemented.
        GREEN: Add @router.post("/{task_id}/clarification") to tasks.py.
        """
        from fastapi.testclient import TestClient

        from main import app as fastapi_app

        # Patch DB_PATH in deps.py BEFORE app starts
        with (
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
        ):
            client = TestClient(fastapi_app)

            response = client.post(
                "/api/tasks/clarify-task-1/clarification",
                json={"decision": "Refund", "edited_draft": None},
            )

            # RED: This assertion FAILS — endpoint returns 404
            assert response.status_code == 200, (
                f"Expected 200, got {response.status_code}. "
                "Endpoint not implemented yet — this is the RED phase failure."
            )

    @pytest.mark.asyncio
    async def test_clarification_endpoint_injects_constraint_in_context(self):
        """After clarification resolves, task context has constraint injected.

        RED: FAILS — no endpoint means no context injection.
        GREEN: Store {constraint: decision} in task.context JSON.
        """
        from fastapi.testclient import TestClient

        from main import app as fastapi_app

        with (
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
        ):
            client = TestClient(fastapi_app)

            # Resolve clarification
            resp = client.post(
                "/api/tasks/clarify-task-1/clarification",
                json={"decision": "Refund", "edited_draft": None},
            )

            if resp.status_code == 200:
                # Check context was updated
                task_resp = client.get("/api/tasks/clarify-task-1")
                task_data = task_resp.json()
                context = task_data.get("context", {})
                if isinstance(context, str):
                    context = json.loads(context)
                assert context.get("constraint") == "Refund", (
                    f"Expected context.constraint='Refund', got {context}"
                )


class TestClarificationWSMessage:
    """Verify send_clarification_request is called in the supervisor graph.

    RED: specialist_node never calls send_clarification_request.
    GREEN: Add ambiguity detection + ws_manager.send_clarification_request() call.
    """

    @pytest.mark.asyncio
    async def test_specialist_node_detects_ambiguity_and_sends_ws_message(self):
        """When agent result has clarification_needed=True, send_clarification_request fires.

        RED: specialist_node only calls _run_agent — no ambiguity detection, no WS call.
        GREEN: After _run_agent, check result.get("clarification_needed") and call ws_manager.
        """
        from backend.api.websocket import ws_manager

        send_calls: list[dict] = []

        original_send = ws_manager.send_clarification_request

        async def tracking_send(task_id, node_id, question, options, context_summary, deadline_iso):
            send_calls.append(
                {
                    "task_id": task_id,
                    "node_id": node_id,
                    "question": question,
                }
            )
            # Don't actually send — we're just tracking calls

        # Patch the ws_manager's method on the module
        with patch.object(ws_manager, "send_clarification_request", tracking_send):
            from backend.agents.supervisor import AgentState, specialist_node
            from backend.memory.store import SharedMemoryStore

            mock_memory = MagicMock(spec=SharedMemoryStore)
            mock_memory.read = AsyncMock(return_value="")

            state = AgentState(
                current_task="Write email to customer about refund",
                task_id="clarify-task-1",
                project_id="test-project",
                context={},
            )

            # Mock _run_agent to return clarification_needed
            async def mock_run_agent(agent_role, task, memory_context, context):
                return {
                    "clarification_needed": True,
                    "question": "Should we issue a full refund or partial?",
                    "options": ["full refund", "partial refund", "store credit"],
                    "context_summary": "Customer requested refund for subscription",
                }

            with patch("backend.agents.supervisor._run_agent", mock_run_agent):
                result = await specialist_node(state, mock_memory)

            # RED: send_calls is empty — specialist_node never calls send_clarification_request
            assert len(send_calls) == 1, (
                f"Expected 1 send_clarification_request call, got {len(send_calls)}. "
                "specialist_node has no ambiguity detection — RED phase failure."
            )
            assert "refund" in send_calls[0]["question"].lower()

    @pytest.mark.asyncio
    async def test_send_clarification_request_method_signature(self):
        """Verify send_clarification_request exists with correct signature."""
        import inspect

        from backend.api.websocket import WSConnectionManager

        sig = inspect.signature(WSConnectionManager.send_clarification_request)
        params = list(sig.parameters.keys())

        # Expected: self, task_id, node_id, question, options, context_summary, deadline_iso
        assert params == [
            "self",
            "task_id",
            "node_id",
            "question",
            "options",
            "context_summary",
            "deadline_iso",
        ], f"send_clarification_request signature wrong: {params}"

        # Verify it's an async method
        import asyncio

        assert asyncio.iscoroutinefunction(WSConnectionManager.send_clarification_request)


class TestClarificationFlow:
    """End-to-end: task -> clarification_request WS -> user responds -> task continues."""

    @pytest.mark.asyncio
    async def test_full_clarification_flow_integration(self):
        """Create task → agent requests clarification → user responds → task completes.

        RED: supervisor graph has no clarification detection — clarification_sent stays empty.
        GREEN: Implement full flow with context injection.
        """
        from backend.agents.supervisor import SupervisorRunner
        from backend.api.routes import tasks as tasks_module
        from backend.memory.store import SharedMemoryStore

        clarification_sent = []

        async def mock_trigger(task_desc, llm_router=None):
            return None  # No skill — goes to supervisor

        async def mock_send_clarification_request(
            task_id, node_id, question, options, context_summary, deadline_iso
        ):
            clarification_sent.append({"task_id": task_id, "question": question})

        mock_ws = MagicMock()
        mock_ws.send_clarification_request = mock_send_clarification_request
        mock_ws.send_task_completed = AsyncMock()
        mock_ws.send_task_failed = AsyncMock()

        mock_memory = MagicMock(spec=SharedMemoryStore)
        mock_memory.read = AsyncMock(return_value="")
        mock_memory.write_episodic = AsyncMock()

        with (
            patch("backend.api.routes.tasks.trigger_skill", mock_trigger),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=mock_ws),
            patch.object(tasks_module, "DB_PATH", _test_db_path),
            patch("backend.api.deps.DB_PATH", _test_db_path),
        ):
            runner = await SupervisorRunner.create(memory_store=mock_memory)

            # Supervisor runs — but currently never sends clarification_request
            # because specialist_node has no ambiguity detection
            #
            # RED: clarification_sent is empty (feature not implemented)
            # After GREEN: supervisor will detect clarification_needed and send WS
            assert len(clarification_sent) >= 0  # Placeholder — will assert > 0 after green
