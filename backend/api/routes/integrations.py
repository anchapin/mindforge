"""Integration management API.

Routes:
  GET    /api/integrations              -> list (status + metadata only, never the token)
  POST   /api/integrations              -> create with Fernet-encrypted token
  DELETE /api/integrations/{id}         -> remove
  POST   /api/integrations/{id}/test    -> probe the integration (best-effort)

Notes:
  - All routes use Depends(db_dep) so FastAPI injects the sqlite3 connection
    instead of treating `db` as an unresolvable query parameter (issue #38).
  - The schema table is `integration` (singular). Older code used `integrations`,
    causing every query to raise OperationalError.
  - permissions/allowed_agents are persisted as JSON arrays, matching how the
    schema columns are read elsewhere in the codebase.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import UTC, datetime

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..deps import db_dep

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrations", tags=["integrations"])

FERNET_KEY = os.getenv("FERNET_KEY", "")
_fernet: Fernet | None = Fernet(FERNET_KEY.encode()) if FERNET_KEY else None


def _encrypt_token(token: str) -> str:
    """Fernet-encrypt a token. Falls back to plaintext only when no key is set
    (test/dev convenience — production must always set FERNET_KEY)."""
    return _fernet.encrypt(token.encode()).decode() if _fernet else token


def _decrypt_token(encrypted: str) -> str:
    if not _fernet:
        return encrypted
    try:
        return _fernet.decrypt(encrypted.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(
            status_code=500, detail="Token decryption failed (rotated key?)"
        ) from exc


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_public(row: sqlite3.Row) -> dict:
    """Project an `integration` row to its safe-to-expose JSON shape.

    Never includes auth_token_enc / refresh_token_enc.
    """

    def _maybe_json(value: str | None) -> list[str]:
        if not value:
            return []
        try:
            return list(json.loads(value))
        except (TypeError, ValueError):
            # Legacy rows persisted with str(list) — try a permissive fallback
            return [v.strip().strip("'\"") for v in value.strip("[]").split(",") if v.strip()]

    return {
        "id": row["id"],
        "app_name": row["app_name"],
        "status": row["status"],
        "permissions": _maybe_json(row["permissions"]),
        "allowed_agents": _maybe_json(row["allowed_agents"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class IntegrationCreate(BaseModel):
    app_name: str = Field(..., min_length=1, max_length=64)
    token: str = Field(..., min_length=1)
    permissions: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)


@router.get("/", response_model=list[dict])
def list_integrations(db: sqlite3.Connection = Depends(db_dep)) -> list[dict]:
    rows = db.execute(
        "SELECT id, app_name, status, permissions, allowed_agents, "
        "created_at, updated_at FROM integration ORDER BY created_at DESC"
    ).fetchall()
    return [_row_to_public(r) for r in rows]


@router.post("/", response_model=dict, status_code=201)
def create_integration(
    payload: IntegrationCreate, db: sqlite3.Connection = Depends(db_dep)
) -> dict:
    integration_id = str(uuid.uuid4())
    encrypted = _encrypt_token(payload.token)
    now = _now_iso()
    try:
        db.execute(
            "INSERT INTO integration "
            "(id, app_name, auth_token_enc, permissions, allowed_agents, "
            "status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
            (
                integration_id,
                payload.app_name,
                encrypted,
                json.dumps(payload.permissions),
                json.dumps(payload.allowed_agents),
                now,
                now,
            ),
        )
        db.commit()
    except sqlite3.IntegrityError as exc:
        # app_name UNIQUE constraint
        raise HTTPException(
            status_code=409, detail=f"Integration '{payload.app_name}' already exists"
        ) from exc

    row = db.execute(
        "SELECT id, app_name, status, permissions, allowed_agents, "
        "created_at, updated_at FROM integration WHERE id = ?",
        (integration_id,),
    ).fetchone()
    return _row_to_public(row)


@router.delete("/{integration_id}", response_model=dict)
def delete_integration(
    integration_id: str, db: sqlite3.Connection = Depends(db_dep)
) -> dict:
    cur = db.execute("DELETE FROM integration WHERE id = ?", (integration_id,))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Integration not found")
    db.commit()
    return {"status": "deleted", "id": integration_id}


@router.post("/{integration_id}/test", response_model=dict)
def test_integration(
    integration_id: str, db: sqlite3.Connection = Depends(db_dep)
) -> dict:
    row = db.execute(
        "SELECT id, app_name, status FROM integration WHERE id = ?",
        (integration_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Integration not found")
    # Phase 1 stub: real connectivity probe is per-tool (see issue #44 / #35).
    return {"success": True, "message": f"{row['app_name']} integration registered"}
