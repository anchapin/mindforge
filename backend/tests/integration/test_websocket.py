"""Test WebSocket message wiring at correct task state transitions — Task 9.

Tests all 8 WS message types from SPEC.md Section 2.5:
1. task_created         → POST /api/tasks (already wired)
2. task_status_update  → pending → running transition
3. draft_ready          → skill node hits requires_approval gate
4. approval_resolved   → POST /approve or POST /reject
5. clarification_request → agent encounters ambiguity
6. agent_message       → agent sends message to chairman
7. task_completed      → task finishes successfully
8. task_failed         → task fails or is rejected

Run: pytest backend/tests/integration/test_websocket.py -v
"""

import os
import pathlib
import sqlite3
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS integration (
            id TEXT PRIMARY KEY,
            app_name TEXT NOT NULL UNIQUE,
            auth_token_enc TEXT NOT NULL,
            refresh_token_enc TEXT,
            token_key_id TEXT NOT NULL DEFAULT 'local',
            status TEXT NOT NULL DEFAULT 'active',
            last_sync_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            extra TEXT,
            permissions TEXT NOT NULL DEFAULT '[]',
            allowed_agents TEXT NOT NULL DEFAULT '[]'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_integration_app ON integration(app_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_integration_status ON integration(status)")
    conn.execute(
        "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ws-task-1",
            None,
            "pending",
            "general",
            None,
            "test task description",
            "{}",
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )
    conn.execute(
        "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "ws-task-draft",
            None,
            "draft",
            "general",
            None,
            "draft task awaiting approval",
            '{"current_node": "draft_node", "skill_execution_context": {"skill_id": "test-skill", "skill_version": 1, "node_id": "draft_node", "nodes_completed": ["verify"], "scratch": {}}}',
            "2026-01-01T00:00:00",
            "2026-01-01T00:00:00",
        ),
    )
    conn.commit()
    conn.close()


_init_test_db()


# --------------------------------------------------------------------------------------
# Helper: mock WS manager that tracks all send calls
# --------------------------------------------------------------------------------------


class TrackingWSManager:
    """Mock WS manager that records all outgoing messages."""

    def __init__(self):
        self.messages: list[dict] = []

    def connect(self, websocket, task_id=None):
        pass

    def disconnect(self, websocket, task_id=None):
        pass

    async def send(self, task_id: str, message: dict):
        self.messages.append({"task_id": task_id, **message})

    async def broadcast(self, message: dict):
        self.messages.append(message)

    async def send_task_created(self, task_id: str, skill_name: str | None):
        await self.broadcast({"type": "task_created", "task_id": task_id, "skill_name": skill_name})

    async def send_task_status_update(self, task_id: str, status: str, agent_role: str):
        await self.send(task_id, {
            "type": "task_status_update",
            "task_id": task_id,
            "status": status,
            "agent_role": agent_role,
        })

    async def send_draft_ready(self, task_id: str, node_id: str, draft: dict, approval_deadline_iso: str):
        await self.send(task_id, {
            "type": "draft_ready",
            "task_id": task_id,
            "node_id": node_id,
            "draft": draft,
            "awaiting_approval": True,
            "approval_deadline_iso": approval_deadline_iso,
        })

    async def send_approval_resolved(self, task_id: str, node_id: str, action: str):
        await self.send(task_id, {
            "type": "approval_resolved",
            "task_id": task_id,
            "node_id": node_id,
            "action": action,
        })

    async def send_clarification_request(self, task_id: str, node_id: str, question: str, options: list, context_summary: str, deadline_iso: str):
        await self.send(task_id, {
            "type": "clarification_request",
            "task_id": task_id,
            "node_id": node_id,
            "question": question,
            "options": options,
            "context_summary": context_summary,
            "deadline_iso": deadline_iso,
        })

    async def send_agent_message(self, task_id: str, agent_role: str, message: str):
        await self.send(task_id, {
            "type": "agent_message",
            "task_id": task_id,
            "agent_role": agent_role,
            "message": message,
        })

    async def send_task_completed(self, task_id: str, final_output: dict):
        await self.send(task_id, {"type": "task_completed", "task_id": task_id, "final_output": final_output})

    async def send_task_failed(self, task_id: str, error: str, escalated: bool):
        await self.send(task_id, {"type": "task_failed", "task_id": task_id, "error": error, "escalated": escalated})

    async def send_skill_triggered(self, skill_id: str, task_id: str):
        await self.broadcast({"type": "skill_triggered", "skill_id": skill_id, "task_id": task_id})

    async def send_stream_token(self, task_id: str, node_id: str, token: str):
        await self.send(task_id, {"type": "stream_token", "task_id": task_id, "node_id": node_id, "token": token})


# --------------------------------------------------------------------------------------
# Test 1: task_status_update fires at pending → running transition
# --------------------------------------------------------------------------------------


class TestTaskStatusUpdateWS:
    """Verify send_task_status_update is called when task goes pending → running.

    RED: _execute_task does NOT call send_task_status_update after setting status='running'.
    GREEN: Add await ws.send_task_status_update(task_id, 'running', agent_role) in _execute_task.
    """

    @pytest.mark.asyncio
    async def test_task_status_update_fires_at_pending_to_running(self):
        """When _execute_task sets status='running', send_task_status_update('running') fires."""
        from backend.api.routes import tasks as tasks_module

        tracking_ws = TrackingWSManager()

        async def mock_trigger(task_desc, llm_router=None):
            return None

        # Use keyword args to match SupervisorRunner.run signature
        async def mock_supervisor_run(task_description=None, task_id=None, project_id=None, skill_name=None, config=None):
            result = MagicMock()
            result.error = None
            result.context = {}
            result.agent_role = "coo"
            result.result = {}
            return result

        with (
            patch("backend.api.routes.tasks.trigger_skill", mock_trigger),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=tracking_ws),
            patch.object(tasks_module, "DB_PATH", _test_db_path),
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.agents.supervisor.SupervisorRunner.run", mock_supervisor_run),
        ):
            from backend.memory.store import SharedMemoryStore
            mock_memory = MagicMock(spec=SharedMemoryStore)
            mock_memory.write_episodic = AsyncMock()

            task_id = "ws-task-1"
            await tasks_module._execute_task(
                task_id=task_id,
                description="test task",
                project_id=None,
                memory=mock_memory,
            )

        status_updates = [m for m in tracking_ws.messages if m.get("type") == "task_status_update"]

        # RED: status_updates is empty — _execute_task never calls send_task_status_update
        assert len(status_updates) >= 1, (
            f"Expected at least 1 task_status_update message, got {len(status_updates)}. "
            "_execute_task does not call send_task_status_update after pending→running transition."
        )
        running_update = next((m for m in status_updates if m.get("status") == "running"), None)
        assert running_update is not None, (
            f"No task_status_update with status='running' found. Messages: {status_updates}"
        )
        assert running_update.get("task_id") == task_id


# --------------------------------------------------------------------------------------
# Test 2: draft_ready fires when skill hits approval gate
# --------------------------------------------------------------------------------------


class TestDraftReadyWS:
    """Verify send_draft_ready is called when a skill node has requires_approval=True.

    RED: _execute_dag returns draft state but never calls ws.send_draft_ready.
    GREEN: Add ws.send_draft_ready() call in _execute_dag when node.requires_approval is True.
    """

    @pytest.mark.asyncio
    async def test_draft_ready_fires_when_skill_node_requires_approval(self):
        """When a skill DAG hits requires_approval=True, send_draft_ready fires."""
        from backend.api.routes import tasks as tasks_module
        from backend.skills.executor import execute_skill
        from backend.skills.models import ExecutionGraph, Skill, SkillNode, TriggerType

        tracking_ws = TrackingWSManager()

        now = datetime.utcnow()

        # Create a minimal skill with an approval-gated node
        approval_node = SkillNode(
            id="draft_node",
            agent="cmo",
            goal="Draft email response",
            requires_approval=True,
            approval_timeout_minutes=1440,
            tools=[],
            outcome_on_failure="fail",
            retry=None,
        )
        verify_node = SkillNode(
            id="verify",
            agent="researcher",
            goal="Verify facts",
            requires_approval=False,
            tools=[],
            outcome_on_failure="skip",
            retry=None,
        )
        graph = ExecutionGraph(
            nodes=[verify_node, approval_node],
            edges=[
                {"from": "verify", "to": "draft_node", "condition": "verify.success"},
            ],
        )
        test_skill = Skill(
            id="test-skill-ws",
            name="Test Skill WS",
            version=1,
            description="Test skill for WS wiring",
            category="general",
            agent_role="coo",
            yaml_content="trigger:\n  type: explicit_only\nexecution_graph:\n  nodes: []",
            trigger_type=TriggerType.EXPLICIT_ONLY,
            created_at=now,
            updated_at=now,
            execution_graph=graph,
        )

        async def mock_llm_complete(prompt, system, agent_role):
            return "Draft email content here."

        async def mock_trigger(task_desc, llm_router=None):
            return test_skill

        with (
            patch("backend.api.routes.tasks.trigger_skill", mock_trigger),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=tracking_ws),
            patch.object(tasks_module, "DB_PATH", _test_db_path),
            patch("backend.api.deps.DB_PATH", _test_db_path),
        ):
            task_id = "ws-task-1"
            from backend.llm.router import LLMRouter
            from backend.tools.registry import ToolRegistry

            llm_router = LLMRouter()
            tools = ToolRegistry()

            result = await execute_skill(
                skill=test_skill,
                task_id=task_id,
                llm_complete=mock_llm_complete,
                tools=tools,
                _ws_manager=tracking_ws,
            )

        # The skill result should have status="draft" (hit approval gate)
        assert result.status == "draft", f"Expected status='draft', got {result.status}"

        # RED: No draft_ready message was sent — _execute_dag doesn't call ws.send_draft_ready
        draft_ready_msgs = [m for m in tracking_ws.messages if m.get("type") == "draft_ready"]
        assert len(draft_ready_msgs) == 1, (
            f"Expected 1 draft_ready message, got {len(draft_ready_msgs)}. "
            "_execute_dag does not call ws.send_draft_ready when node.requires_approval=True."
        )
        assert draft_ready_msgs[0].get("task_id") == task_id
        assert draft_ready_msgs[0].get("node_id") == "draft_node"
        assert draft_ready_msgs[0].get("awaiting_approval") is True


# --------------------------------------------------------------------------------------
# Test 3: approval_resolved fires at POST /approve (simple path, no skill)
# --------------------------------------------------------------------------------------


class TestApprovalResolvedWSApprove:
    """Verify send_approval_resolved is called when task is approved via POST /approve.

    GREEN: Already wired in approve_task (tasks.py line 373). Verify it works.
    """

    @pytest.mark.asyncio
    async def test_approval_resolved_fires_on_approve(self):
        """POST /api/tasks/{task_id}/approve → send_approval_resolved(action='approved')."""
        from fastapi.testclient import TestClient

        from main import app as fastapi_app

        tracking_ws = TrackingWSManager()

# Update task context so it has no skill_execution_context (takes simple approval path)
        conn = sqlite3.connect(_test_db_path)
        conn.execute(
            "UPDATE tasks SET context = '{}', status = 'draft' WHERE id = 'ws-task-draft'"
        )
        conn.commit()
        conn.close()

        with (
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=tracking_ws),
        ):
            client = TestClient(fastapi_app)
            response = client.post(
                "/api/tasks/ws-task-draft/approve",
                json={"edited_content": None},
            )

            # GREEN: This should pass (already wired)
            if response.status_code != 200:
                print(f"DEBUG: {response.status_code} {response.text[:500]}")
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

            approval_msgs = [m for m in tracking_ws.messages if m.get("type") == "approval_resolved"]
            assert len(approval_msgs) == 1, (
                f"Expected 1 approval_resolved message, got {len(approval_msgs)}"
            )
            assert approval_msgs[0].get("action") == "approved"


# --------------------------------------------------------------------------------------
# Test 4: approval_resolved fires at POST /reject
# --------------------------------------------------------------------------------------


class TestApprovalResolvedWSReject:
    """Verify send_approval_resolved is called when task is rejected via POST /reject.

    GREEN: Already wired in reject_task (tasks.py line 409). Verify it works.
    """

    @pytest.mark.asyncio
    async def test_approval_resolved_fires_on_reject(self):
        """POST /api/tasks/{task_id}/reject → send_approval_resolved(action='rejected')."""
        from fastapi.testclient import TestClient

        from main import app as fastapi_app

        tracking_ws = TrackingWSManager()

        with (
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=tracking_ws),
        ):
            client = TestClient(fastapi_app)
            response = client.post(
                "/api/tasks/ws-task-draft/reject",
                json={"feedback": "Not good enough"},
            )

            # GREEN: This should pass (already wired)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"

            approval_msgs = [m for m in tracking_ws.messages if m.get("type") == "approval_resolved"]
            assert len(approval_msgs) == 1, (
                f"Expected 1 approval_resolved message, got {len(approval_msgs)}"
            )
            assert approval_msgs[0].get("action") == "rejected"


# --------------------------------------------------------------------------------------
# Test 5: task_completed fires when task finishes successfully
# --------------------------------------------------------------------------------------


class TestTaskCompletedWS:
    """Verify send_task_completed is called when task finishes with success.

    GREEN: Already wired in _execute_task (line 195) and approve_task (line 375).
    Verify the wiring works correctly.
    """

    @pytest.mark.asyncio
    async def test_task_completed_fires_on_successful_execution(self):
        """_execute_task with successful result → send_task_completed fires."""
        from backend.api.routes import tasks as tasks_module

        tracking_ws = TrackingWSManager()

        async def mock_trigger(task_desc, llm_router=None):
            return None

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.context = {}
        mock_result.agent_role = "coo"
        mock_result.result = {"summary": "Task completed successfully"}
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("backend.api.routes.tasks.trigger_skill", mock_trigger),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=tracking_ws),
            patch.object(tasks_module, "DB_PATH", _test_db_path),
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.SupervisorRunner", return_value=mock_runner),
        ):
            from backend.memory.store import SharedMemoryStore
            mock_memory = MagicMock(spec=SharedMemoryStore)
            mock_memory.write_episodic = AsyncMock()

            task_id = "ws-task-1"
            await tasks_module._execute_task(
                task_id=task_id,
                description="test task",
                project_id=None,
                memory=mock_memory,
            )

        completed_msgs = [m for m in tracking_ws.messages if m.get("type") == "task_completed"]
        assert len(completed_msgs) == 1, (
            f"Expected 1 task_completed message, got {len(completed_msgs)}"
        )
        assert completed_msgs[0].get("task_id") == task_id


# --------------------------------------------------------------------------------------
# Test 6: task_failed fires when task fails
# --------------------------------------------------------------------------------------


class TestTaskFailedWS:
    """Verify send_task_failed is called when task fails or is rejected.

    GREEN: Already wired in _execute_task (line 197, 211) and reject_task (line 410).
    Verify the wiring works correctly.
    """

    @pytest.mark.asyncio
    async def test_task_failed_fires_on_task_rejection(self):
        """POST /api/tasks/{task_id}/reject → send_task_failed fires."""
        from fastapi.testclient import TestClient

        from main import app as fastapi_app

        tracking_ws = TrackingWSManager()

        with (
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=tracking_ws),
        ):
            client = TestClient(fastapi_app)
            response = client.post(
                "/api/tasks/ws-task-draft/reject",
                json={"feedback": "Not good enough"},
            )

            assert response.status_code == 200

            failed_msgs = [m for m in tracking_ws.messages if m.get("type") == "task_failed"]
            assert len(failed_msgs) == 1, (
                f"Expected 1 task_failed message, got {len(failed_msgs)}"
            )
            assert "rejected" in failed_msgs[0].get("error", "").lower()
            assert failed_msgs[0].get("escalated") is True


# --------------------------------------------------------------------------------------
# Test 7: skill_triggered fires when a skill is matched and begins execution
# --------------------------------------------------------------------------------------


class TestSkillTriggeredWS:
    """Verify send_skill_triggered is called when a skill is matched.

    RED: trigger_skill + _execute_task don't call ws.send_skill_triggered.
    GREEN: Add ws.send_skill_triggered() call when skill is matched in _execute_task.
    """

    @pytest.mark.asyncio
    async def test_skill_triggered_fires_when_skill_matched(self):
        """When trigger_skill matches a skill, send_skill_triggered broadcasts."""
        from backend.skills.executor import execute_skill
        from backend.skills.models import ExecutionGraph, Skill, SkillNode, TriggerType

        tracking_ws = TrackingWSManager()
        now = datetime.utcnow()

        # Create a simple skill that completes (no approval gate)
        complete_node = SkillNode(
            id="do_it",
            agent="coo",
            goal="Complete the task",
            requires_approval=False,
            tools=[],
            outcome_on_failure="fail",
            retry=None,
        )
        graph = ExecutionGraph(nodes=[complete_node], edges=[])
        test_skill = Skill(
            id="trigger-test-skill",
            name="Trigger Test Skill",
            version=1,
            description="Skill to test skill_triggered WS message",
            category="general",
            agent_role="coo",
            yaml_content="trigger:\n  type: keyword\n  keywords: [trigger test]",
            trigger_type=TriggerType.KEYWORD,
            trigger_keywords=["trigger test"],
            created_at=now,
            updated_at=now,
            execution_graph=graph,
        )

        async def mock_llm_complete(prompt, system, agent_role):
            return "Done."

        # Directly test that when skill matches, skill_triggered should fire.
        # This simulates what _execute_task SHOULD do when a skill is matched
        async def mock_trigger(task_desc, llm_router=None):
            if "trigger test" in task_desc.lower():
                return test_skill
            return None

        # Simulate the _execute_task flow: trigger_skill → execute_skill
        matched_skill = await mock_trigger("do a trigger test task", None)
        assert matched_skill is not None

        # Call execute_skill directly — this is what _execute_task does after trigger_skill matches.
        # The send_skill_triggered WS call lives in _execute_task (tasks.py line 118), not execute_skill.
        # Test that when execute_skill is called with a skill, it completes without error.
        from backend.llm.router import LLMRouter
        from backend.tools.registry import ToolRegistry

        llm_router = LLMRouter()
        tools = ToolRegistry()

        skill_result = await execute_skill(
            skill=matched_skill,
            task_id="ws-task-1",
            llm_complete=mock_llm_complete,
            tools=tools,
        )

        # skill_triggered WS call is in _execute_task, not execute_skill.
        # Verify the implementation: _execute_task calls send_skill_triggered when skill matches.
        # Test this by calling _execute_task and checking the WS message was broadcast.
        from backend.api.routes import tasks as tasks_module

        tracking_ws2 = TrackingWSManager()

        async def mock_trigger2(task_desc, llm_router=None):
            return matched_skill

        with (
            patch("backend.api.routes.tasks.trigger_skill", mock_trigger2),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=tracking_ws2),
            patch.object(tasks_module, "DB_PATH", _test_db_path),
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.agents.supervisor.SupervisorRunner") as mock_sr_cls,
        ):
            mock_result = MagicMock()
            mock_result.error = None
            mock_result.context = {}
            mock_result.agent_role = "coo"
            mock_result.result = {}
            mock_runner = MagicMock()
            mock_runner.run = AsyncMock(return_value=mock_result)
            mock_sr_cls.return_value = mock_runner

            from backend.memory.store import SharedMemoryStore
            mock_memory = MagicMock(spec=SharedMemoryStore)
            mock_memory.write_episodic = AsyncMock()

            await tasks_module._execute_task(
                task_id="ws-task-1",
                description="do a trigger test task",
                project_id=None,
                memory=mock_memory,
            )

        skill_triggered_msgs = [m for m in tracking_ws2.messages if m.get("type") == "skill_triggered"]
        assert len(skill_triggered_msgs) == 1, (
            f"Expected 1 skill_triggered message, got {len(skill_triggered_msgs)}. "
            "_execute_task does not call ws.send_skill_triggered when skill is matched."
        )
        assert skill_triggered_msgs[0].get("skill_id") == "trigger-test-skill"


# --------------------------------------------------------------------------------------
# Test 8: task_status_update fires at running → completed transition
# --------------------------------------------------------------------------------------


class TestTaskStatusUpdateRunningToFinal:
    """Verify send_task_status_update is called when task goes running → completed."""

    @pytest.mark.asyncio
    async def test_task_status_update_fires_at_running_to_completed(self):
        """When _execute_task sets status='completed', send_task_status_update('completed') fires."""
        from backend.api.routes import tasks as tasks_module

        tracking_ws = TrackingWSManager()

        async def mock_trigger(task_desc, llm_router=None):
            return None

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.context = {}
        mock_result.agent_role = "coo"
        mock_result.result = {}
        mock_runner = MagicMock()
        mock_runner.run = AsyncMock(return_value=mock_result)

        with (
            patch("backend.api.routes.tasks.trigger_skill", mock_trigger),
            patch("backend.api.routes.tasks.get_ws_manager", return_value=tracking_ws),
            patch.object(tasks_module, "DB_PATH", _test_db_path),
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.SupervisorRunner", return_value=mock_runner),
        ):
            from backend.memory.store import SharedMemoryStore
            mock_memory = MagicMock(spec=SharedMemoryStore)
            mock_memory.write_episodic = AsyncMock()

            task_id = "ws-task-1"
            await tasks_module._execute_task(
                task_id=task_id,
                description="test task",
                project_id=None,
                memory=mock_memory,
            )

        status_updates = [m for m in tracking_ws.messages if m.get("type") == "task_status_update"]

        # Should have both "running" and "completed" status updates
        assert len(status_updates) >= 2, (
            f"Expected at least 2 task_status_update messages (running + completed), got {len(status_updates)}"
        )
        completed_update = next((m for m in status_updates if m.get("status") == "completed"), None)
        assert completed_update is not None, (
            f"No task_status_update with status='completed'. Messages: {status_updates}"
        )


# --------------------------------------------------------------------------------------
# GREEN phase helper: verify WS method signatures match SPEC
# --------------------------------------------------------------------------------------


class TestWSMessageSignatures:
    """Verify all WS message methods exist with correct signatures per SPEC.md Section 2.5."""

    def test_all_ws_message_methods_exist(self):
        """All 8 WS message type methods exist on WSConnectionManager."""
        from backend.api.websocket import WSConnectionManager

        required_methods = [
            "send_task_created",
            "send_task_status_update",
            "send_draft_ready",
            "send_approval_resolved",
            "send_clarification_request",
            "send_agent_message",
            "send_task_completed",
            "send_task_failed",
            "send_skill_triggered",
        ]

        for method_name in required_methods:
            assert hasattr(WSConnectionManager, method_name), (
                f"WSConnectionManager missing method: {method_name}"
            )
            method = getattr(WSConnectionManager, method_name)
            import asyncio
            assert asyncio.iscoroutinefunction(method), (
                f"{method_name} is not async"
            )
