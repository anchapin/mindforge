"""Database migration runner. From SPEC.md Section 5e.6."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "mindforge.db")


# In-place column adds for tables that already exist on alpha installs.
# SQLite has no ADD COLUMN IF NOT EXISTS, so we check pragma_table_info first.
_INPLACE_COLUMN_ADDITIONS: list[tuple[str, str, str]] = [
    # (table, column, ALTER TABLE clause)
    ("user_preference", "onboarding_completed",
     "ALTER TABLE user_preference ADD COLUMN onboarding_completed INTEGER NOT NULL DEFAULT 0"),
    # writing_profile.created_at was missing from schema.sql even though the
    # onboarding route INSERTs it; the route used to silently fail at runtime.
    # Default to current time so legacy rows get a sensible stamp.
    ("writing_profile", "created_at",
     "ALTER TABLE writing_profile ADD COLUMN created_at TEXT NOT NULL DEFAULT (datetime('now'))"),
]


def _apply_inplace_column_additions(conn: sqlite3.Connection) -> None:
    """For each (table, column) tuple, add the column if it doesn't already
    exist. Lets us evolve schemas without dropping data on alpha installs."""
    for table, column, alter_sql in _INPLACE_COLUMN_ADDITIONS:
        # Skip if the table doesn't exist yet (the CREATE TABLE in schema.sql
        # will create it with the column already in place)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        if not exists:
            continue
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            logger.info("migrate: adding %s.%s", table, column)
            conn.execute(alter_sql)


def run_migrations(db_path: str | None = None) -> None:
    """Run all migrations from schema.sql. For Phase 1, direct SQL execution (not full Alembic)."""
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    if not os.path.exists(SCHEMA_PATH):
        logger.warning("schema.sql not found at %s -- skipping migrations", SCHEMA_PATH)
        return

    schema_sql = Path(SCHEMA_PATH).read_text()
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # Add new columns to existing tables BEFORE re-running CREATE TABLE
        # (the CREATE is IF NOT EXISTS so it's a no-op when the table exists).
        _apply_inplace_column_additions(conn)
        conn.executescript(schema_sql)
        conn.commit()
    logger.info("Migrations applied: %s", path)


def reset_db(db_path: str | None = None) -> None:
    """Drop all tables and re-run migrations. FOR TESTING ONLY."""
    path = db_path or DB_PATH
    with sqlite3.connect(path) as conn:
        tables = [
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if r["name"] not in ("sqlite_sequence",)
        ]
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    run_migrations(path)
    logger.warning("Database reset: %s", path)
