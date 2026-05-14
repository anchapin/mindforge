"""Memory API endpoints -- semantic, episodic, writing style layers."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ...memory.store import SharedMemoryStore
from ..deps import db_dep, memory_dep

router = APIRouter(prefix="/api/memories", tags=["memories"])


class SemanticAdd(BaseModel):
    text: str
    project_id: str | None = None


class EpisodicAdd(BaseModel):
    project_id: str | None = None
    task_id: str
    task_type: str
    agent_role: str
    summary: str
    outcome_status: str
    feedback: str | None = None


class StyleUpdate(BaseModel):
    tone: str | None = None
    sentence_length: str | None = None
    first_person: str | None = None
    signature_phrases: list[str] | None = None
    greeting_style: str | None = None
    signoff_style: str | None = None


@router.get("/semantic")
async def search_semantic(
    q: str = Query(..., min_length=1),
    project_id: str | None = None,
    top_k: int = 5,
    memory: SharedMemoryStore = Depends(memory_dep),
):
    records = await memory._semantic.retrieve(query=q, project_id=project_id, top_k=top_k)
    return {
        "query": q,
        "project_id": project_id,
        "count": len(records),
        "records": [
            {"id": r.id, "text": r.text, "project_id": r.project_id, "metadata": r.metadata}
            for r in records
        ],
    }


@router.post("/semantic")
async def add_semantic(payload: SemanticAdd, memory: SharedMemoryStore = Depends(memory_dep)):
    ids = await memory.write_semantic(text=payload.text, project_id=payload.project_id)
    return {"ids": ids, "count": len(ids)}


@router.get("/episodic")
def get_episodic(
    project_id: str | None = None,
    task_type: str | None = None,
    limit: int = 20,
    db=Depends(db_dep),
):
    rows = db.execute(
        "SELECT * FROM episodic_memory WHERE (? IS NULL OR project_id = ?) "
        "AND (? IS NULL OR task_type = ?) ORDER BY created_at DESC LIMIT ?",
        (project_id, project_id, task_type, task_type, limit),
    ).fetchall()
    return {"count": len(rows), "records": [dict(r) for r in rows]}


@router.post("/episodic")
async def add_episodic(payload: EpisodicAdd, memory: SharedMemoryStore = Depends(memory_dep)):
    from ...memory.episodic import EpisodicMemory

    record = EpisodicMemory(
        id=str(uuid.uuid4()),
        project_id=payload.project_id,
        task_id=payload.task_id,
        task_type=payload.task_type,
        agent_role=payload.agent_role,
        summary=payload.summary,
        outcome_status=payload.outcome_status,
        feedback=payload.feedback,
        created_at=datetime.utcnow(),
    )
    await memory.write_episodic(record)
    return {"id": record.id}


@router.get("/style")
def get_style(memory: SharedMemoryStore = Depends(memory_dep)):
    return memory.get_writing_profile().get().to_dict()


@router.put("/style")
def update_style(payload: StyleUpdate, memory: SharedMemoryStore = Depends(memory_dep)):
    updates = payload.model_dump(exclude_none=True)
    profile = memory.get_writing_profile().update_style(updates)
    return profile.to_dict()


@router.delete("/all")
async def delete_all_memories(
    confirm: bool = False,
    memory: SharedMemoryStore = Depends(memory_dep),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Must set confirm=true")
    result = memory.delete_all_memories()
    return {"deleted": True, **result}
