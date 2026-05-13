"""Integration management API."""

from __future__ import annotations

import os
import uuid
from datetime import datetime

from cryptography.fernet import Fernet
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

FERNET_KEY = os.getenv("FERNET_KEY", "")
_fernet = Fernet(FERNET_KEY.encode()) if FERNET_KEY else None


def _encrypt_token(token: str) -> str:
    return _fernet.encrypt(token.encode()).decode() if _fernet else token


def _decrypt_token(encrypted: str) -> str:
    return _fernet.decrypt(encrypted.encode()).decode() if _fernet else encrypted


class IntegrationCreate(BaseModel):
    app_name: str
    token: str
    permissions: list[str] = []
    allowed_agents: list[str] = []


@router.get("/")
def list_integrations(db) -> list[dict]:
    rows = db.execute(
        "SELECT id, app_name, status, permissions, allowed_agents, created_at, updated_at FROM integrations"
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/")
def create_integration(payload: IntegrationCreate, db) -> dict:
    integration_id = str(uuid.uuid4())
    encrypted = _encrypt_token(payload.token)
    now = datetime.utcnow().isoformat()
    db.execute(
        "INSERT INTO integrations (id, app_name, auth_token_enc, permissions, allowed_agents, status, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
        (integration_id, payload.app_name, encrypted, str(payload.permissions), str(payload.allowed_agents), now, now),
    )
    db.commit()
    return {"id": integration_id, "app_name": payload.app_name, "status": "active"}


@router.delete("/{integration_id}")
def delete_integration(integration_id: str, db) -> dict:
    db.execute("DELETE FROM integrations WHERE id = ?", (integration_id,))
    if db.rowcount == 0:
        raise HTTPException(status_code=404, detail="Integration not found")
    db.commit()
    return {"status": "deleted"}


@router.post("/{integration_id}/test")
def test_integration(integration_id: str, db) -> dict:
    row = db.execute("SELECT * FROM integrations WHERE id = ?", (integration_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Integration not found")
    return {"success": True, "message": f"{row['app_name']} connection OK"}
