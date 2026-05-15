"""Memory API endpoints -- semantic, episodic, writing style layers."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ...memory.store import SharedMemoryStore
from ..deps import memory_dep

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
async def get_episodic(
    project_id: str | None = None,
    task_type: str | None = None,
    limit: int = 20,
    memory: SharedMemoryStore = Depends(memory_dep),
):
    """Get episodic memories - uses async SQLite via SharedMemoryStore."""
    records = await memory._episodic.query_by_project(
        project_id=project_id,
        task_type=task_type,
        limit=limit,
    )
    return {"count": len(records), "records": [r.to_dict() for r in records]}


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
async def get_style(memory: SharedMemoryStore = Depends(memory_dep)):
    profile = await memory._style.get()
    return profile.to_dict()


@router.put("/style")
async def update_style(payload: StyleUpdate, memory: SharedMemoryStore = Depends(memory_dep)):
    updates = payload.model_dump(exclude_none=True)
    profile = await memory._style.update_style(updates)
    return profile.to_dict()


@router.delete("/all")
async def delete_all_memories(
    confirm: bool = False,
    memory: SharedMemoryStore = Depends(memory_dep),
):
    if not confirm:
        raise HTTPException(status_code=400, detail="Must set confirm=true")
    result = await memory.delete_all_memories()
    return {"deleted": True, **result}


# ---------------------------------------------------------------------------
# Per-record deletion (#53, PRIVACY.md / SPEC §3b.5)
# ---------------------------------------------------------------------------


@router.delete("/semantic/{record_id}")
async def delete_semantic_record(
    record_id: str,
    memory: SharedMemoryStore = Depends(memory_dep),
):
    """Drop a single semantic memory record from ChromaDB (#53)."""
    if not memory._semantic.has(record_id) if hasattr(memory._semantic, "has") else False:
        # If the underlying store doesn't expose has(), fall back to a
        # count-before / count-after check so we still honour the 404
        # contract for unknown ids.
        before = memory._semantic.count()
        memory._semantic.delete(record_id)
        after = memory._semantic.count()
        if before == after:
            raise HTTPException(status_code=404, detail="semantic record not found")
        return {"deleted": True, "id": record_id, "count_after": after}

    memory._semantic.delete(record_id)
    return {
        "deleted": True,
        "id": record_id,
        "count_after": memory._semantic.count(),
    }


@router.delete("/episodic/{record_id}")
async def delete_episodic_record(
    record_id: str,
    cascade_steps: bool = Query(False, description="Delete dependent task_step rows"),
    memory: SharedMemoryStore = Depends(memory_dep),
):
    """Drop a single episodic memory row (#53).

    Dependent ``task_step`` rows for the same ``task_id`` are blocking by
    default -- the route returns 409 with the count of blocking rows.
    Pass ``?cascade_steps=true`` to delete those rows alongside the
    episodic record.
    """
    task_id = await memory._episodic.get_task_id(record_id)
    if task_id is None:
        raise HTTPException(status_code=404, detail="episodic record not found")

    dep_count = await memory._episodic.count_dependent_steps(task_id)
    cascaded = 0
    if dep_count and not cascade_steps:
        raise HTTPException(
            status_code=409,
            detail=(
                f"episodic record {record_id} has {dep_count} dependent task_step row(s) "
                f"for task_id={task_id}; pass ?cascade_steps=true to remove them"
            ),
        )

    if dep_count and cascade_steps:
        cascaded = await memory._episodic.delete_dependent_steps(task_id)

    rowcount = await memory._episodic.delete(record_id)
    if rowcount == 0:
        # Race: another request deleted the row between get_task_id() and now.
        raise HTTPException(status_code=404, detail="episodic record not found")

    return {
        "deleted": True,
        "id": record_id,
        "task_id": task_id,
        "cascaded_steps": cascaded,
    }


@router.delete("/style")
async def reset_style(memory: SharedMemoryStore = Depends(memory_dep)):
    """Reset the writing profile to spec defaults (#53). Idempotent."""
    profile = await memory._style.reset()
    return {"reset": True, "profile": profile.to_dict()}
