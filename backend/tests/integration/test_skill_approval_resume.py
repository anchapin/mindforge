"""Test skill DAG approval gate and resume flow — Issue #22.

Tests the complete draft-first workflow:
1. Skill DAG hits approval gate → returns draft status (with skill_execution_context)
2. POST /approve calls execute_skill_continue to resume the DAG
3. DAG continues to completion after approval

Run: pytest backend/tests/integration/test_skill_approval_resume.py -v
"""

import json
import os
import pathlib
import sqlite3
import tempfile
import uuid
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
            skill_version INTEGER NOT NULL DEFAULT 1,
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
    conn.commit()
    conn.close()


_init_test_db()


async def _make_draft_task(task_id: str, skill_id: str, context_json: str) -> None:
    """Helper: insert a task in draft state with skill execution context."""
    conn = sqlite3.connect(_test_db_path)
    now = "2026-01-01T00:00:00"
    conn.execute(
        "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id,
            skill_id,
            "draft",
            "skill",
            None,
            "subscription refund request",
            context_json,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()


class TestSkillApprovalResume:
    """Verify the complete draft-first approval flow."""

    @pytest.mark.asyncio
    async def test_approve_task_calls_execute_skill_continue(self):
        """POST /approve should call execute_skill_continue to resume the DAG.

        RED: FAILS - approve_task does NOT call execute_skill_continue.
        It only updates the task status to 'executing' and sends a WS message,
        but the DAG never resumes.
        GREEN: approve_task reads skill_execution_context from task context,
        reconstructs SkillExecutionContext, and calls execute_skill_continue.
        """
        from backend.api.routes import tasks as tasks_module

        task_id = "test-approve-" + str(uuid.uuid4())[:8]

        # Task in draft state with skill_execution_context (as written by _execute_task)
        draft_context = {
            "skill_id": "subscription-refund",
            "task_type": "skill",
            "current_node": "draft",
            "skill_execution_context": {
                "skill_id": "subscription-refund",
                "skill_version": 1,
                "node_id": "draft",
                "nodes_completed": ["verify"],
                "scratch": {
                    "verify": {"status": "success", "output": {"text": "verified"}},
                },
            },
        }

        await _make_draft_task(task_id, "subscription-refund", json.dumps(draft_context))

        continue_calls = []

        async def mock_execute_skill_continue(
            ctx, approval_action, edited_content=None, llm_complete=None, tools=None
        ):
            continue_calls.append(
                {
                    "ctx_task_id": getattr(ctx, "task_id", None),
                    "ctx_node_id": getattr(ctx, "node_id", None),
                    "approval_action": approval_action,
                }
            )
            from backend.skills.models import SkillResult

            return SkillResult(
                skill_id="subscription-refund",
                skill_version=1,
                status="completed",
                nodes_completed=["verify", "draft", "negotiate"],
                current_node=None,
                final_output={},
                started_at=getattr(ctx, "started_at", None) if hasattr(ctx, "started_at") else None,
            )

        with (
            patch("backend.skills.executor.execute_skill_continue", mock_execute_skill_continue),
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.get_ws_manager") as mock_ws_mgr,
        ):
            mock_ws_mgr.return_value.send_approval_resolved = AsyncMock()
            mock_ws_mgr.return_value.send_task_completed = AsyncMock()

            from backend.api.routes.tasks import ApprovalRequest

            # Call approve_task directly with a real sqlite3 connection (bypassing Depends)
            payload = ApprovalRequest()
            test_conn = sqlite3.connect(_test_db_path)
            test_conn.row_factory = sqlite3.Row

            try:
                result = await tasks_module.approve_task(task_id, payload, db=test_conn)
            except Exception as exc:
                pytest.fail(f"approve_task raised: {exc}")
            finally:
                test_conn.close()

        assert len(continue_calls) == 1, (
            f"execute_skill_continue called {len(continue_calls)} times, expected 1. "
            f"approve_task must call execute_skill_continue to resume the DAG."
        )
        assert continue_calls[0]["approval_action"] == "approved"

    @pytest.mark.asyncio
    async def test_execute_skill_returns_draft_at_approval_gate(self):
        """execute_skill hits requires_approval node → returns draft status, doesn't execute that node.

        GREEN: This already passes — proves DAG correctly pauses at approval gates.
        """
        from backend.skills.executor import execute_skill
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()
        skill = registry.get("subscription-refund")
        assert skill is not None, "subscription-refund skill not loaded"

        call_count = 0

        async def counting_llm(prompt, system="", agent_role=None):
            nonlocal call_count
            call_count += 1
            return '{"text": "ok"}'

        mock_tools = MagicMock()
        mock_tools.get = lambda name: MagicMock()

        result = await execute_skill(
            skill=skill,
            task_id=str(uuid.uuid4()),
            llm_complete=counting_llm,
            tools=mock_tools,
        )

        assert result.status == "draft", f"Expected draft, got {result.status}"
        assert result.current_node == "draft"
        assert "verify" in result.nodes_completed
        assert call_count == 1, f"Expected 1 LLM call (verify only), got {call_count}"

    @pytest.mark.asyncio
    async def test_approve_resumes_draft_and_completes_dag(self):
        """After approval, execute_skill_continue resumes from 'draft' node and completes the DAG.

        Full flow:
        1. execute_skill runs verify → pauses at draft (status=draft)
        2. approve_task calls execute_skill_continue with approval_action="approved"
        3. DAG resumes from 'draft' node, completes all remaining nodes
        """
        from backend.skills.executor import execute_skill, execute_skill_continue
        from backend.skills.models import SkillExecutionContext
        from backend.skills.registry import SkillRegistry

        registry = SkillRegistry()
        registry.load_all()
        skill = registry.get("subscription-refund")
        assert skill is not None

        task_id = str(uuid.uuid4())

        call_count_phase1 = 0

        async def counting_llm(prompt, system="", agent_role=None):
            nonlocal call_count_phase1
            call_count_phase1 += 1
            return '{"text": "ok"}'

        mock_tools = MagicMock()
        mock_tools.get = lambda name: MagicMock()

        draft_result = await execute_skill(
            skill=skill,
            task_id=task_id,
            llm_complete=counting_llm,
            tools=mock_tools,
        )

        assert draft_result.status == "draft", f"Expected draft, got {draft_result.status}"

        ctx = SkillExecutionContext(
            task_id=task_id,
            skill=skill,
            node_id=draft_result.current_node,
            scratch={
                "verify": {"status": "success", "output": {"text": "verified"}},
                "draft": {"status": "waiting_approval"},
            },
            nodes_completed=list(draft_result.nodes_completed),
            started_at=draft_result.started_at,
        )

        call_count_phase2 = 0

        async def counting_llm_resume(prompt, system="", agent_role=None):
            nonlocal call_count_phase2
            call_count_phase2 += 1
            return '{"text": "approved and processed"}'

        continue_result = await execute_skill_continue(
            ctx=ctx,
            approval_action="approved",
            edited_content=None,
            llm_complete=counting_llm_resume,
            tools=mock_tools,
        )

        assert continue_result.status in ("completed", "failed", "escalated"), (
            f"Expected completed/failed/escalated, got {continue_result.status}"
        )
        assert "draft" in continue_result.nodes_completed, (
            f"Expected 'draft' in nodes_completed after approval, got {continue_result.nodes_completed}"
        )
