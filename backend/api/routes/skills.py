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
from backend.skills.validator import validate_skill_graph

router = APIRouter(prefix="/api/skills", tags=["skills"])
logger = logging.getLogger(__name__)


class SkillCreate(BaseModel):
    name: str
    yaml_content: str


class SkillRunRequest(BaseModel):
    description: str
    project_id: str | None = None


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


class SkillValidate(BaseModel):
    yaml_content: str


@router.post("/validate", response_model=dict)
def validate_skill(payload: SkillValidate) -> dict:
    """Validate skill YAML without persisting it. Used by SkillEditor (#49)
    for live validation feedback as the user types.

    Returns:
      { "valid": bool, "errors": list[str], "graph": {nodes, edges} | None }

    `graph` is included so the editor can render a live DAG preview
    without re-parsing the YAML on the client.
    """
    try:
        skill_def = yaml.safe_load(payload.yaml_content)
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [f"YAML parse error: {exc}"], "graph": None}
    if not isinstance(skill_def, dict):
        return {
            "valid": False,
            "errors": ["YAML must parse to a mapping (got "
                       f"{type(skill_def).__name__})"],
            "graph": None,
        }
    errors = validate_skill_graph(skill_def)
    # Surface the parsed graph for the DAG preview, even when invalid —
    # the editor can render whatever structure made it past parsing so
    # the user can spot the broken edge visually.
    graph_dict = (
        skill_def.get("execution_graph")
        if "execution_graph" in skill_def
        else {"nodes": skill_def.get("nodes", []), "edges": skill_def.get("edges", [])}
    )
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "graph": graph_dict,
    }


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


class SkillUpdate(BaseModel):
    name: str
    yaml_content: str


@router.put("/{skill_id}", response_model=dict)
def update_skill(skill_id: str, payload: SkillUpdate) -> dict:
    """PUT /api/skills/{skill_id} — update an existing skill's YAML on disk.

    From SPEC.md Section 2.3 — the SkillEditor (#49) uses this to persist edits
    made in the YAML editor. The skill file is rewritten, then the in-memory
    registry is reloaded so the change takes effect immediately.

    Returns 404 if the skill_id is not found in the registry.
    """
    registry = get_registry()
    existing = registry.get(skill_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    try:
        skill_def = yaml.safe_load(payload.yaml_content)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"YAML parse error: {exc}")
    errors = validate_skill_graph(skill_def)
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    skill_file = registry._skills_dir / f"{skill_id}.yaml"
    skill_file.write_text(payload.yaml_content)

    reloaded = registry.load_skill_file(skill_file)
    if reloaded is None:
        raise HTTPException(status_code=500, detail=f"Failed to reload skill '{skill_id}' after update")

    return reloaded.model_dump(mode="json")
