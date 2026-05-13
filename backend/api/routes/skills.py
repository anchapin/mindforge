"""Skill registry and validation API."""

from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/skills", tags=["skills"])
logger = logging.getLogger(__name__)


class SkillCreate(BaseModel):
    name: str
    yaml_content: str


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


@router.get("/")
def list_skills():
    return []


@router.post("/validate")
def validate_skill(yaml_content: str) -> dict:
    try:
        skill_def = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [f"YAML parse error: {exc}"]}
    errors = validate_skill_graph(skill_def)
    return {"valid": len(errors) == 0, "errors": errors}


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
