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
        runner = SupervisorRunner(memory)
        result = await runner.run(
            task_description=description,
            task_id=task_id,
            project_id=project_id,
        )
        final_status = "completed" if result.error is None else "failed"

        record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id=project_id,
            task_id=task_id,
            task_type=result.context.get("task_type", "general"),
            agent_role=result.agent_role,
            summary=result.result.get("summary", description) if result.result else description,
            outcome_status=final_status,
            created_at=datetime.utcnow(),
        )
        await memory.write_episodic(record)

        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ?, completed_at = ?, context = ? WHERE id = ?",
            (final_status, datetime.utcnow().isoformat(), datetime.utcnow().isoformat(),
             json.dumps(result.context), task_id),
        )
        conn.commit()
        conn.close()

        ws = get_ws_manager()
        if final_status == "completed":
            await ws.send_task_completed(task_id, result.result or {})
        else:
            await ws.send_task_failed(task_id, result.error or "unknown", False)

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
