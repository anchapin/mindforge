"""Skill registry and validation API — Task 8.

Wires GET /api/skills catalog to SkillRegistry.list().
GET /api/skills/{id} returns full Skill with execution_graph.
POST /api/skills/{id}/run creates a task for the skill.

From SPEC.md Section 2.3 + plan-gap-analysis.json Task 8.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.api.deps import DB_PATH, db_dep, get_ws_manager, memory_dep
from backend.skills.registry import get_registry

router = APIRouter(prefix="/api/skills", tags=["skills"])
logger = logging.getLogger(__name__)


class SkillCreate(BaseModel):
    name: str
    yaml_content: str


class SkillRunRequest(BaseModel):
    description: str
    project_id: str | None = None


def validate_skill_graph(skill_def: dict) -> list[str]:
    """Validate skill execution graph. Returns list of errors; empty = valid."""
    errors: list[str] = []
    node_ids = {n["id"] for n in skill_def.get("nodes", [])}
    outgoing: dict[str, list[str]] = {n["id"]: [] for n in skill_def.get("nodes", [])}

    for edge in skill_def.get("edges", []):
        if edge["from"] not in node_ids:
            errors.append(f"Edge references missing node: {edge['from']}")
        if edge["to"] not in node_ids:
            errors.append(f"Edge references missing node: {edge['to']}")
        outgoing[edge["from"]].append(edge.get("condition", ""))

    for node in skill_def.get("nodes", []):
        if node.get("requires_approval") and not outgoing.get(node["id"]):
            errors.append(f"Node '{node['id']}' requires approval but has no outgoing edges")

    def has_path(from_id: str, visited: set[str]) -> bool:
        if from_id in visited:
            errors.append(f"Cycle detected: {from_id}")
            return True
        for edge in skill_def.get("edges", []):
            if edge["from"] == from_id:
                if has_path(edge["to"], visited | {from_id}):
                    return True
        return False

    for node in skill_def.get("nodes", []):
        if not any(e["to"] == node["id"] for e in skill_def.get("edges", [])):
            if has_path(node["id"], set()):
                break

    return errors


@router.get("/", response_model=list[dict])
def list_skills() -> list[dict]:
    """GET /api/skills — return catalog of all loaded skills as SkillMetadata list.

    Returns all fields from SkillMetadata (id, name, description, category,
    version, tools, memory_layers, trigger_type, trigger_keywords, trigger_intents,
    success_count, failure_count, last_run_at).
    """
    registry = get_registry()
    metadata_list = registry.list()
    return [m.model_dump(mode="json") for m in metadata_list]


@router.post("/validate")
def validate_skill(yaml_content: str) -> dict:
    try:
        skill_def = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [f"YAML parse error: {exc}"]}
    errors = validate_skill_graph(skill_def)
    return {"valid": len(errors) == 0, "errors": errors}


@router.get("/{skill_id}", response_model=dict)
def get_skill(skill_id: str) -> dict:
    """GET /api/skills/{skill_id} — return full Skill with execution_graph.

    Returns 404 if skill not found.
    """
    registry = get_registry()
    skill = registry.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    return skill.model_dump(mode="json")


@router.post("/{skill_id}/run", response_model=dict)
async def run_skill(
    skill_id: str,
    payload: SkillRunRequest,
    db=Depends(db_dep),
    _memory=Depends(memory_dep),
    ws=Depends(get_ws_manager),
) -> dict:
    """POST /api/skills/{skill_id}/run — create a task for the given skill and execute it.

    Creates a task in the DB with the skill's skill_id, then starts background
    execution via the skill executor. Sends task_created and skill_triggered WS messages.
    """
    registry = get_registry()
    skill = registry.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    task_id = str(uuid.uuid4())
    now = datetime.utcnow().isoformat()

    db.execute(
        "INSERT INTO tasks (id, skill_id, status, task_type, project_id, description, context, created_at, updated_at) "
        "VALUES (?, ?, 'pending', 'general', ?, ?, '{}', ?, ?)",
        (task_id, skill_id, payload.project_id, payload.description, now, now),
    )
    db.commit()

    await ws.send_task_created(task_id, skill_name=skill.name)
    await ws.send_skill_triggered(skill_id, task_id)

    asyncio.create_task(_run_skill_task(task_id, skill_id, skill.agent_role, payload.project_id))

    row = db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_task(row)


async def _run_skill_task(
    task_id: str,
    skill_id: str,
    agent_role: str,
    project_id: str | None,
) -> None:
    """Background runner for a skill-based task.

    Updates task to running, delegates to execute_skill(), then updates final status.
    """
    import sqlite3

    from backend.api.websocket import WSConnectionManager
    from backend.llm.router import LLMRouter
    from backend.skills.executor import execute_skill
    from backend.skills.registry import get_registry
    from backend.tools.registry import ToolRegistry

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE tasks SET status = 'running', updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), task_id),
    )
    conn.commit()
    conn.close()

    ws = WSConnectionManager()
    await ws.send_task_status_update(task_id, "running", agent_role)

    try:
        registry = get_registry()
        skill_obj = registry.get(skill_id)
        if not skill_obj:
            return

        llm_router = LLMRouter()
        tools = ToolRegistry()

        result = await execute_skill(
            skill=skill_obj,
            task_id=task_id,
            llm_complete=llm_router.complete,
            tools=tools,
            _ws_manager=ws,
        )

        final_status = "completed" if result.status in ("completed", "approved") else "failed"
        result_dict = result.model_dump(mode="json") if hasattr(result, "model_dump") else {}
        ctx = {"skill_id": skill_id, "skill_result": result_dict}

        _update_task_status(task_id, final_status, ctx)
        await ws.send_task_completed(task_id, result.final_output or {})

    except Exception as exc:
        _update_task_status(task_id, "failed", {"error": str(exc)})
        await ws.send_task_failed(task_id, str(exc), False)


def _update_task_status(task_id: str, status: str, context: dict) -> None:
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    ctx_json = json.dumps(context)
    now = datetime.utcnow().isoformat()
    completed = now if status in ("completed", "failed") else None
    conn.execute(
        "UPDATE tasks SET status = ?, context = ?, updated_at = ?, completed_at = ? WHERE id = ?",
        (status, ctx_json, now, completed, task_id),
    )
    conn.commit()
    conn.close()


def _row_to_task(row) -> dict:
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


@router.post("/")
def create_skill(payload: SkillCreate) -> dict:
    try:
        skill_def = yaml.safe_load(payload.yaml_content)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"YAML parse error: {exc}")
    errors = validate_skill_graph(skill_def)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    return {"id": skill_def.get("name", payload.name), "status": "created"}
