"""Task CRUD API endpoints.

Status values: pending | running | draft | approved | executing | completed | failed
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...agents.supervisor import SupervisorRunner
from ...memory.episodic import EpisodicMemory
from ...memory.store import SharedMemoryStore
from ...skills.trigger import trigger_skill
from ..deps import DB_PATH, db_dep, get_ws_manager, memory_dep

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    description: str
    skill_id: str | None = None
    project_id: str | None = None


class ApprovalRequest(BaseModel):
    edited_content: dict[str, Any] | None = None


class RejectRequest(BaseModel):
    feedback: str


def _row_to_task(row) -> dict[str, Any]:
    ctx = json.loads(row["context"]) if isinstance(row["context"], str) else (row["context"] or {})
    return {
        "id": row["id"],
        "skill_id": row["skill_id"],
        "status": row["status"],
        "task_type": row["task_type"],
        "project_id": row["project_id"],
        "description": row["description"],
        "context": ctx,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


@router.get("/", response_model=list[dict])
def list_tasks(status: str | None = None, project_id: str | None = None, db=Depends(db_dep)):
    query = "SELECT * FROM tasks WHERE 1=1"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if project_id:
        query += " AND project_id = ?"
        params.append(project_id)
    query += " ORDER BY created_at DESC LIMIT 100"
    rows = db.execute(query, params).fetchall()
    return [_row_to_task(r) for r in rows]


@router.post("/", response_model=dict)
async def create_task(payload: TaskCreate, db=Depends(db_dep), memory: SharedMemoryStore = Depends(memory_dep)):
    task_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) "
        "VALUES (?, ?, 'pending', 'general', ?, ?, '{}', ?, ?)",
        (task_id, payload.skill_id, payload.project_id, payload.description, now, now),
    )
    db.commit()

    ws = get_ws_manager()
    await ws.send_task_created(task_id, skill_name=None)

    asyncio.create_task(_execute_task(task_id, payload.description, payload.project_id, memory))

    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_task(row)


async def _execute_task(task_id: str, description: str, project_id: str | None, memory: SharedMemoryStore):
    """Background task runner -- starts supervisor and updates task on completion."""

    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE tasks SET status = 'running', updated_at = ? WHERE id = ?",
                 (datetime.utcnow().isoformat(), task_id))
    conn.commit()
    conn.close()

    try:
        # Try to trigger a skill first (SPEC.md Section 2.3)
        matched_skill = await trigger_skill(description)

        if matched_skill is not None:
            # Skill matched — execute it through the DAG
            from ...llm.router import LLMRouter
            from ...skills.executor import execute_skill
            from ...tools.registry import ToolRegistry

            llm_router = LLMRouter()
            tools = ToolRegistry()

            skill_result = await execute_skill(
                skill=matched_skill,
                task_id=task_id,
                llm_complete=llm_router.complete,
                tools=tools,
            )

            # Map skill result to agent result
            final_status = "completed" if skill_result.status in ("completed", "draft") else "failed"
            result_context = {
                "skill_id": matched_skill.id,
                "task_type": "skill",
                "current_node": skill_result.current_node,
                "draft_content": skill_result.draft_content,
                # Persist execution context for approval gate resume
                "skill_execution_context": {
                    "skill_id": matched_skill.id,
                    "skill_version": matched_skill.version,
                    "node_id": skill_result.current_node,
                    "nodes_completed": skill_result.nodes_completed,
                    "scratch": skill_result.final_output or {},
                },
            }
            agent_role = matched_skill.agent_role or "skill-executor"
            result_summary = {"status": skill_result.status, "nodes_completed": skill_result.nodes_completed}
            skill_error = skill_result.error
        else:
            # No skill matched — fall back to supervisor
            runner = SupervisorRunner(memory)
            result = await runner.run(
                task_description=description,
                task_id=task_id,
                project_id=project_id,
            )
            final_status = "completed" if result.error is None else "failed"
            result_context = result.context or {}
            agent_role = result.agent_role
            result_summary = result.result or {}
            skill_error = result.error

        record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=task_id,
            task_type=str(result_context.get("task_type", "general")),  # type: ignore[arg-type]
            agent_role=agent_role,
            summary=str(result_summary.get("summary", description)) if result_summary else description,  # type: ignore[arg-type]
            outcome_status=final_status,
            created_at=datetime.utcnow(),
        )
        await memory.write_episodic(record)

        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ?, context = ? WHERE id = ?",
            (final_status, datetime.utcnow().isoformat(), datetime.utcnow().isoformat(),
             json.dumps(result_context), task_id),
        )
        conn.commit()
        conn.close()

        ws = get_ws_manager()
        if final_status == "completed":
            await ws.send_task_completed(task_id, result_summary or {})
        else:
            await ws.send_task_failed(task_id, skill_error or "unknown", False)

    except Exception as exc:
        import traceback
        traceback.print_exc()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE tasks SET status = 'failed', updated_at = ? WHERE id = ?",
                     (datetime.utcnow().isoformat(), task_id))
        conn.commit()
        conn.close()
        ws = get_ws_manager()
        await ws.send_task_failed(task_id, str(exc), False)


class ClarificationRequest(BaseModel):
    decision: str
    edited_draft: dict[str, Any] | None = None


@router.post("/{task_id}/clarification")
async def clarify_task(
    task_id: str,
    payload: ClarificationRequest,
    db=Depends(db_dep),
    ws=Depends(get_ws_manager),
):
    """Resolve a clarification request from the dashboard.

    Receives the user's decision (and optionally an edited draft) and injects
    it into the task context so the agent can continue with resolved ambiguity.

    From SPEC.md Section 2.5 — clarification_response from dashboard.
    """
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    ctx = json.loads(task["context"]) if task["context"] else {}

    # Inject the clarification decision as a constraint
    ctx["constraint"] = payload.decision

    # If user edited the draft, store it
    if payload.edited_draft is not None:
        ctx["draft_content"] = payload.edited_draft
        ctx["user_modified_draft"] = True

    # Update task context and set status back to running
    db.execute(
        "UPDATE tasks SET status = 'running', updated_at = ?, context = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), json.dumps(ctx), task_id),
    )
    db.commit()

    await ws.send(
        task_id,
        {
            "type": "clarification_resolved",
            "task_id": task_id,
            "decision": payload.decision,
            "edited_draft": payload.edited_draft,
        },
    )

    return {"status": "clarification_resolved", "constraint": payload.decision}


@router.get("/{task_id}")
def get_task(task_id: str, db=Depends(db_dep)):
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return _row_to_task(row)


@router.post("/{task_id}/approve")
async def approve_task(task_id: str, payload: ApprovalRequest, db=Depends(db_dep)):
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "draft":
        raise HTTPException(status_code=400, detail="Task is not in draft state")

    ctx = json.loads(task["context"]) if task["context"] else {}
    if payload.edited_content:
        ctx["draft_content"] = payload.edited_content
        ctx["user_modified_draft"] = True

    # If skill_execution_context exists, resume the DAG via execute_skill_continue
    exec_ctx_raw = ctx.get("skill_execution_context")
    if exec_ctx_raw:
        from ...llm.router import LLMRouter
        from ...skills.executor import execute_skill_continue
        from ...skills.models import SkillExecutionContext
        from ...skills.registry import get_registry

        registry = get_registry()
        skill = registry.get(exec_ctx_raw["skill_id"])
        if skill is None:
            raise HTTPException(status_code=400, detail=f"Skill not found: {exec_ctx_raw['skill_id']}")

        # Reconstruct SkillExecutionContext from persisted state
        skill_ctx = SkillExecutionContext(
            task_id=task_id,
            skill=skill,
            node_id=exec_ctx_raw["node_id"],
            scratch=exec_ctx_raw.get("scratch", {}),
            nodes_completed=exec_ctx_raw.get("nodes_completed", []),
            started_at=datetime.utcnow(),  # started_at is not persisted; use now for continue
        )

        llm_router = LLMRouter()
        from ...tools.registry import ToolRegistry
        tools = ToolRegistry()

        continue_result = await execute_skill_continue(
            ctx=skill_ctx,
            approval_action="approved",
            edited_content=payload.edited_content,
            llm_complete=llm_router.complete,
            tools=tools,
        )

        # Update task with the continued result
        final_status = "completed" if continue_result.status in ("completed", "draft") else "failed"
        ctx["current_node"] = continue_result.current_node
        ctx["skill_execution_context"] = {
            "skill_id": skill.id,
            "skill_version": skill.version,
            "node_id": continue_result.current_node,
            "nodes_completed": continue_result.nodes_completed,
            "scratch": continue_result.final_output or skill_ctx.scratch,
        }
        if continue_result.error:
            ctx["skill_error"] = continue_result.error

        db.execute(
            "UPDATE tasks SET status = ?, updated_at = ?, context = ?, completed_at = ? WHERE id = ?",
            (final_status, datetime.utcnow().isoformat(), json.dumps(ctx),
             datetime.utcnow().isoformat() if final_status == "completed" else None, task_id),
        )
        db.commit()

        # Style learning: extract writing profile from approved content
        try:
            from ...memory.style import WritingProfileStore, extract_style_fields
            style_store = WritingProfileStore()
            # Use edited content if provided, otherwise extract from draft scratch
            if payload.edited_content:
                content = payload.edited_content.get("text", "") or payload.edited_content.get("content", "")
            else:
                draft_node = skill_ctx.scratch.get("draft", {})
                output = draft_node.get("output", {})
                content = output.get("text", "") if isinstance(output, dict) else str(output or "")
            if content:
                style_fields = await extract_style_fields(content, llm_router.complete)
                if style_fields:
                    style_store.update_style(style_fields)
        except Exception:
            pass  # Style learning is best-effort; never fail approval due to it

        ws = get_ws_manager()
        await ws.send_approval_resolved(task_id, skill_ctx.node_id, "approved")
        if final_status == "completed":
            await ws.send_task_completed(task_id, {"status": continue_result.status})
        else:
            await ws.send_task_failed(task_id, continue_result.error or "unknown", False)

        return {"status": "approved", "skill_status": continue_result.status}

    # No skill context — fall back to simple approval (non-skill task approval)
    db.execute(
        "UPDATE tasks SET status = 'executing', updated_at = ?, context = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), json.dumps(ctx), task_id),
    )
    db.commit()

    ws = get_ws_manager()
    await ws.send_approval_resolved(task_id, ctx.get("current_node", ""), "approved")
    return {"status": "approved"}


@router.post("/{task_id}/reject")
async def reject_task(task_id: str, payload: RejectRequest, db=Depends(db_dep)):
    task = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    ctx = json.loads(task["context"]) if task["context"] else {}
    ctx["rejection_feedback"] = payload.feedback

    db.execute(
        "UPDATE tasks SET status = 'failed', updated_at = ?, context = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), json.dumps(ctx), task_id),
    )
    db.commit()

    ws = get_ws_manager()
    await ws.send_approval_resolved(task_id, ctx.get("current_node", ""), "rejected")
    await ws.send_task_failed(task_id, f"Rejected: {payload.feedback}", True)
    return {"status": "rejected"}


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, db=Depends(db_dep)):
    db.execute(
        "UPDATE tasks SET status = 'failed', updated_at = ?, context = context || ? WHERE id = ?",
        (datetime.utcnow().isoformat(), '{"escalation_message": "Cancelled by user"}', task_id),
    )
    db.commit()
    return {"status": "cancelled"}
