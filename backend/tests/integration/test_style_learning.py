"""Test writing style learning on task approval — Issue #20.

When a skill-based task is approved (with or without edits), the system should:
1. Extract writing style fields via LLM (extract_style_fields)
2. Update the WritingProfile store with the extracted fields

Run: pytest backend/tests/integration/test_style_learning.py -v
"""

import json
import os
import pathlib
import sqlite3
import tempfile
import uuid
from unittest.mock import AsyncMock, patch

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
        CREATE TABLE IF NOT EXISTS writing_profile (
            id TEXT PRIMARY KEY,
            tone TEXT NOT NULL DEFAULT 'semi-formal',
            sentence_length TEXT NOT NULL DEFAULT 'medium',
            first_person TEXT NOT NULL DEFAULT 'I',
            signature_phrases TEXT NOT NULL DEFAULT '[]',
            greeting_style TEXT NOT NULL DEFAULT 'Hi [Name],',
            signoff_style TEXT NOT NULL DEFAULT 'Cheers',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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


class TestStyleLearning:
    """Verify style extraction on task approval."""

    @pytest.mark.asyncio
    async def test_approve_with_edits_extracts_style_from_edited_content(self):
        """When user edits the draft, style is extracted from the EDITED version.

        RED: FAIL — style learning not yet wired into approve_task.
        GREEN: Wire extract_style_fields into approve_task. Use edited_content["text"]
               as source. Call style_store.update_style() with extracted fields.
        """
        from backend.api.routes import tasks as tasks_module
        from backend.memory.style import WritingProfileStore

        task_id = "test-style-edit-" + str(uuid.uuid4())[:8]

        draft_context = {
            "skill_id": "subscription-refund",
            "task_type": "skill",
            "current_node": "negotiate",
            "skill_execution_context": {
                "skill_id": "subscription-refund",
                "skill_version": 1,
                "node_id": "draft",
                "nodes_completed": ["verify", "draft"],
                "scratch": {
                    "verify": {"status": "success", "output": {"text": "verified"}},
                    "draft": {
                        "status": "waiting_approval",
                        "output": {"text": "Hi team,\n\nI'd like to request a refund."},
                    },
                    "negotiate": {
                        "status": "completed",
                        "output": {"text": "The refund has been approved."},
                    },
                },
                "final_output": {"text": "The refund has been processed."},
            },
        }

        await _make_draft_task(task_id, "subscription-refund", json.dumps(draft_context))

        update_style_calls = []

        async def mock_execute_skill_continue(
            ctx, approval_action, edited_content=None, llm_complete=None, tools=None,
            agent_identity=None, integration_configs=None
        ):
            from datetime import datetime

            from backend.skills.models import SkillResult

            return SkillResult(
                skill_id="subscription-refund",
                skill_version=1,
                status="completed",
                nodes_completed=["verify", "draft", "negotiate"],
                current_node=None,
                final_output={"text": "The refund has been processed."},
                started_at=datetime.utcnow(),
            )

        async def mock_extract(content, llm_complete):
            # Verify we get the EDITED content, not the original draft
            assert "Hey team" in content, f"Expected edited content, got: {content[:50]}"
            return {
                "tone": "casual",
                "sentence_length": "short",
                "first_person": "I",
                "signature_phrases": ["cheers", "all the best"],
                "greeting_style": "Hey team,",
                "signoff_style": "Cheers",
            }

        # update_style is synchronous — use a regular function, not async def
        def mock_update_style(self_arg, updates):
            update_style_calls.append(updates)
            return WritingProfileStore(db_path=self_arg.db_path).get()

        with (
            patch("backend.skills.executor.execute_skill_continue", mock_execute_skill_continue),
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.get_ws_manager") as mock_ws_mgr,
            patch("backend.memory.style.extract_style_fields", mock_extract),
            patch("backend.memory.style.WritingProfileStore.update_style", mock_update_style),
        ):
            mock_ws_mgr.return_value.send_approval_resolved = AsyncMock()
            mock_ws_mgr.return_value.send_task_completed = AsyncMock()

            from backend.api.routes.tasks import ApprovalRequest

            # User edited the draft before approving
            edited_draft = {
                "text": "Hey team,\n\nI'm reaching out about a refund. Can we sort this out quickly? Cheers!"
            }
            payload = ApprovalRequest(edited_content=edited_draft)

            test_conn = sqlite3.connect(_test_db_path)
            test_conn.row_factory = sqlite3.Row

            try:
                result = await tasks_module.approve_task(task_id, payload, db=test_conn)
            except AttributeError as exc:
                pytest.fail(f"Style learning not wired into approve_task: {exc}")
            finally:
                test_conn.close()

        assert len(update_style_calls) == 1, (
            f"update_style called {len(update_style_calls)} times, expected 1"
        )
        extracted = update_style_calls[0]
        assert extracted["tone"] == "casual", f"Expected tone='casual', got {extracted.get('tone')}"
        assert extracted["greeting_style"] == "Hey team,", (
            f"Expected greeting_style='Hey team,', got {extracted.get('greeting_style')}"
        )

    @pytest.mark.asyncio
    async def test_approve_without_edits_extracts_style_from_draft(self):
        """When user approves without edits, style is extracted from scratch['draft']['output']['text'].

        RED: FAIL — style learning not using scratch['draft']['output']['text'] as fallback.
        GREEN: Use scratch['draft']['output']['text'] as content source when no edited_content.
        """
        from backend.api.routes import tasks as tasks_module
        from backend.memory.style import WritingProfileStore

        task_id = "test-style-no-edit-" + str(uuid.uuid4())[:8]

        draft_context = {
            "skill_id": "subscription-refund",
            "task_type": "skill",
            "current_node": "negotiate",
            "skill_execution_context": {
                "skill_id": "subscription-refund",
                "skill_version": 1,
                "node_id": "draft",
                "nodes_completed": ["verify", "draft"],
                "scratch": {
                    "verify": {"status": "success", "output": {"text": "verified"}},
                    "draft": {
                        "status": "waiting_approval",
                        "output": {
                            "text": "Hi team,\n\nI am requesting a refund for my subscription. Please advise."
                        },
                    },
                    "negotiate": {
                        "status": "completed",
                        "output": {"text": "Refund approved."},
                    },
                },
            },
        }

        await _make_draft_task(task_id, "subscription-refund", json.dumps(draft_context))

        update_style_calls = []

        async def mock_execute_skill_continue(
            ctx, approval_action, edited_content=None, llm_complete=None, tools=None,
            agent_identity=None, integration_configs=None
        ):
            from datetime import datetime

            from backend.skills.models import SkillResult

            return SkillResult(
                skill_id="subscription-refund",
                skill_version=1,
                status="completed",
                nodes_completed=["verify", "draft", "negotiate"],
                current_node=None,
                final_output={},
                started_at=datetime.utcnow(),
            )

        async def mock_extract(content, llm_complete):
            # Verify we get the original draft output, not final output
            assert "Hi team" in content, f"Expected original draft content, got: {content[:50]}"
            return {
                "tone": "semi-formal",
                "sentence_length": "medium",
                "first_person": "I",
                "signature_phrases": [],
                "greeting_style": "Hi team,",
                "signoff_style": "Thanks",
            }

        def mock_update_style(self_arg, updates):
            update_style_calls.append(updates)
            return WritingProfileStore(db_path=self_arg.db_path).get()

        with (
            patch("backend.skills.executor.execute_skill_continue", mock_execute_skill_continue),
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.get_ws_manager") as mock_ws_mgr,
            patch("backend.memory.style.extract_style_fields", mock_extract),
            patch("backend.memory.style.WritingProfileStore.update_style", mock_update_style),
        ):
            mock_ws_mgr.return_value.send_approval_resolved = AsyncMock()
            mock_ws_mgr.return_value.send_task_completed = AsyncMock()

            from backend.api.routes.tasks import ApprovalRequest

            payload = ApprovalRequest()  # No edited_content

            test_conn = sqlite3.connect(_test_db_path)
            test_conn.row_factory = sqlite3.Row

            try:
                result = await tasks_module.approve_task(task_id, payload, db=test_conn)
            except AttributeError as exc:
                pytest.fail(f"Style learning not wired: {exc}")
            finally:
                test_conn.close()

        assert len(update_style_calls) == 1, (
            f"update_style called {len(update_style_calls)} times, expected 1"
        )

    @pytest.mark.asyncio
    async def test_style_extraction_llm_returns_valid_fields(self):
        """extract_style_fields returns all WritingProfile fields from LLM response.

        RED: FAIL — extract_style_fields doesn't exist yet.
        GREEN: Implement in backend/memory/style.py. Call LLM with style-extraction
               prompt. Parse JSON response. Return dict with all WritingProfile fields.
        """
        from backend.memory.style import extract_style_fields

        content = "Hi team,\n\nI'm asking for a refund. Can you help? Cheers!"

        async def mock_llm(prompt, system="", agent_role=None):
            return json.dumps(
                {
                    "tone": "casual",
                    "sentence_length": "short",
                    "first_person": "I",
                    "signature_phrases": ["cheers"],
                    "greeting_style": "Hi team,",
                    "signoff_style": "Cheers",
                }
            )

        result = await extract_style_fields(content, mock_llm)

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert all(
            k in result
            for k in (
                "tone",
                "sentence_length",
                "first_person",
                "signature_phrases",
                "greeting_style",
                "signoff_style",
            )
        )
        assert result["tone"] == "casual"
        assert result["signature_phrases"] == ["cheers"]

    @pytest.mark.asyncio
    async def test_non_skill_task_approval_does_not_trigger_style_learning(self):
        """Approval of a non-skill task (no skill_execution_context) skips style learning.

        RED: FAIL — style learning not yet gated on skill_execution_context presence.
        GREEN: Only call extract_style_fields when ctx["skill_execution_context"] exists.
        """
        from backend.api.routes import tasks as tasks_module

        task_id = "test-no-style-" + str(uuid.uuid4())[:8]

        # Non-skill task — no skill_execution_context
        conn = sqlite3.connect(_test_db_path)
        now = "2026-01-01T00:00:00"
        conn.execute(
            "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (task_id, None, "draft", "general", None, "simple task", json.dumps({}), now, now),
        )
        conn.commit()
        conn.close()

        extract_calls = []

        async def mock_extract(content, llm_complete):
            extract_calls.append(content)
            return {}

        with (
            patch("backend.api.deps.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.DB_PATH", _test_db_path),
            patch("backend.api.routes.tasks.get_ws_manager") as mock_ws_mgr,
            patch("backend.memory.style.extract_style_fields", mock_extract),
        ):
            mock_ws_mgr.return_value.send_approval_resolved = AsyncMock()

            from backend.api.routes.tasks import ApprovalRequest

            payload = ApprovalRequest()

            test_conn = sqlite3.connect(_test_db_path)
            test_conn.row_factory = sqlite3.Row

            try:
                result = await tasks_module.approve_task(task_id, payload, db=test_conn)
            finally:
                test_conn.close()

        # Style learning should NOT be called for non-skill tasks
        assert len(extract_calls) == 0, (
            f"extract_style_fields called {len(extract_calls)} times for non-skill task — "
            "style learning must be gated on skill_execution_context presence"
        )
