"""Onboarding API — POST /api/onboarding.

From SPEC.md Section 2.3 + plan-gap-analysis.json Task 7.
OnboardingWizard step 3 calls this to create WritingProfile and Integration records.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..deps import db_dep

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

FERNET_KEY = os.getenv("FERNET_KEY", "")
_fernet = Fernet(FERNET_KEY.encode()) if FERNET_KEY else None


def _encrypt_token(token: str) -> str:
    return _fernet.encrypt(token.encode()).decode() if _fernet else token


class WritingStyleInput(BaseModel):
    tone: str | None = None
    sentence_length: str | None = None
    first_person: str | None = None
    signature_phrases: list[str] | None = None
    greeting_style: str | None = None
    signoff_style: str | None = None


class IntegrationInput(BaseModel):
    app_name: str
    token: str
    permissions: list[str] = []
    allowed_agents: list[str] = []


class OnboardingPayload(BaseModel):
    writing_style: WritingStyleInput
    integrations: list[IntegrationInput] = []


def complete_onboarding(payload: OnboardingPayload, db) -> dict:
    """POST /api/onboarding — create or update WritingProfile and Integration records.

    Called by OnboardingWizard step 3 after user has filled in writing style preferences
    and added integration credentials. Uses upsert logic to handle re-onboarding.
    """
    now = datetime.utcnow().isoformat()

    # --- Writing Profile: upsert ---
    # Get existing id or None
    existing_wp = db.execute("SELECT id FROM writing_profile LIMIT 1").fetchone()

    tone = payload.writing_style.tone or "semi-formal"
    sentence_length = payload.writing_style.sentence_length or "medium"
    first_person = payload.writing_style.first_person or "I"
    signature_phrases = json.dumps(payload.writing_style.signature_phrases or [])
    greeting_style = payload.writing_style.greeting_style or "Hi [Name],"
    signoff_style = payload.writing_style.signoff_style or "Cheers"

    if existing_wp:
        db.execute(
            "UPDATE writing_profile SET "
            "tone = ?, sentence_length = ?, first_person = ?, "
            "signature_phrases = ?, greeting_style = ?, signoff_style = ?, "
            "updated_at = ? "
            "WHERE id = ?",
            (tone, sentence_length, first_person, signature_phrases,
             greeting_style, signoff_style, now, existing_wp["id"]),
        )
    else:
        wp_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO writing_profile "
            "(id, tone, sentence_length, first_person, signature_phrases, "
            "greeting_style, signoff_style, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (wp_id, tone, sentence_length, first_person, signature_phrases,
             greeting_style, signoff_style, now, now),
        )

    # --- Integrations: upsert by app_name ---
    for integ in payload.integrations:
        existing = db.execute(
            "SELECT id FROM integrations WHERE app_name = ?", (integ.app_name,)
        ).fetchone()

        encrypted = _encrypt_token(integ.token)
        permissions = json.dumps(integ.permissions)
        allowed_agents = json.dumps(integ.allowed_agents)

        if existing:
            db.execute(
                "UPDATE integrations SET "
                "auth_token_enc = ?, permissions = ?, allowed_agents = ?, "
                "updated_at = ? "
                "WHERE app_name = ?",
                (encrypted, permissions, allowed_agents, now, integ.app_name),
            )
        else:
            integ_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO integrations "
                "(id, app_name, auth_token_enc, permissions, allowed_agents, "
                "status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'active', ?, ?)",
                (integ_id, integ.app_name, encrypted, permissions, allowed_agents, now, now),
            )

    db.commit()
    return {"status": "created"}


@router.post("/", response_model=dict)
async def post_onboarding(payload: OnboardingPayload, db=Depends(db_dep)) -> dict:
    """POST /api/onboarding — complete onboarding wizard."""
    return complete_onboarding(payload, db)
