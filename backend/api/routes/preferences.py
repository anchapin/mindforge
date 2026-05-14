"""UserPreference API — GET/PUT /api/preferences.

From SPEC.md Section 2.3 + plan-gap-analysis.json Task 7.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import db_dep

router = APIRouter(prefix="/api/preferences", tags=["preferences"])


class PreferencesUpdate(BaseModel):
    proactive_monitoring_enabled: bool | None = None
    email_check_interval_minutes: int | None = None
    calendar_check_interval_minutes: int | None = None
    billing_alert_threshold_usd: int | None = None
    notification_channel: str | None = None
    notification_handle: str | None = None


def get_preferences(db) -> dict:
    """GET /api/preferences — return the UserPreference singleton with defaults.

    Returns all fields from the user_preference table. If the singleton row doesn't
    exist yet, returns defaults matching the schema defaults.
    """
    row = db.execute("SELECT * FROM user_preference LIMIT 1").fetchone()

    if row:
        return {
            "id": row["id"],
            "proactive_monitoring_enabled": bool(row["proactive_monitoring_enabled"]),
            "email_check_interval_minutes": row["email_check_interval_minutes"],
            "calendar_check_interval_minutes": row["calendar_check_interval_minutes"],
            "billing_alert_threshold_usd": row["billing_alert_threshold_usd"],
            "notification_channel": row["notification_channel"],
            "notification_handle": row["notification_handle"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # Singleton not yet created — return defaults
    return {
        "id": "",
        "proactive_monitoring_enabled": True,
        "email_check_interval_minutes": 30,
        "calendar_check_interval_minutes": 60,
        "billing_alert_threshold_usd": 50,
        "notification_channel": "dashboard",
        "notification_handle": None,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }


@router.get("/", response_model=dict)
def list_preferences(db=Depends(db_dep)) -> dict:
    """GET /api/preferences — return current user preferences."""
    return get_preferences(db)


def update_preferences(payload: PreferencesUpdate, db) -> dict:
    """PUT /api/preferences — partial update of the UserPreference singleton.

    Only fields set in payload are updated; all others are preserved.
    """
    row = db.execute("SELECT id FROM user_preference LIMIT 1").fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="UserPreference singleton not found")

    pref_id = row["id"]
    now = datetime.utcnow().isoformat()

    # Build dynamic UPDATE from non-None fields
    updates: list[str] = ["updated_at = ?"]
    params: list = [now]

    if payload.proactive_monitoring_enabled is not None:
        updates.append("proactive_monitoring_enabled = ?")
        params.append(int(payload.proactive_monitoring_enabled))  # store as 0/1

    if payload.email_check_interval_minutes is not None:
        updates.append("email_check_interval_minutes = ?")
        params.append(payload.email_check_interval_minutes)

    if payload.calendar_check_interval_minutes is not None:
        updates.append("calendar_check_interval_minutes = ?")
        params.append(payload.calendar_check_interval_minutes)

    if payload.billing_alert_threshold_usd is not None:
        updates.append("billing_alert_threshold_usd = ?")
        params.append(payload.billing_alert_threshold_usd)

    if payload.notification_channel is not None:
        updates.append("notification_channel = ?")
        params.append(payload.notification_channel)

    if payload.notification_handle is not None:
        updates.append("notification_handle = ?")
        params.append(payload.notification_handle)

    params.append(pref_id)
    db.execute(f"UPDATE user_preference SET {', '.join(updates)} WHERE id = ?", params)
    db.commit()

    # Return updated preferences
    updated_row = db.execute("SELECT * FROM user_preference WHERE id = ?", (pref_id,)).fetchone()
    return {
        "status": "updated",
        "preferences": {
            "proactive_monitoring_enabled": bool(updated_row["proactive_monitoring_enabled"]),
            "email_check_interval_minutes": updated_row["email_check_interval_minutes"],
            "calendar_check_interval_minutes": updated_row["calendar_check_interval_minutes"],
            "billing_alert_threshold_usd": updated_row["billing_alert_threshold_usd"],
            "notification_channel": updated_row["notification_channel"],
            "notification_handle": updated_row["notification_handle"],
        },
    }


@router.put("/", response_model=dict)
def put_preferences(payload: PreferencesUpdate, db=Depends(db_dep)) -> dict:
    """PUT /api/preferences — partial update of user preferences."""
    return update_preferences(payload, db)
