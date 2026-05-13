"""Database migration runner. From SPEC.md Section 5e.6."""

from __future__ import annotations
import os
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
DATA_DIR = os.getenv("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "mindforge.db")


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
        conn.executescript(schema_sql)
        conn.commit()
    logger.info("Migrations applied: %s", path)


def reset_db(db_path: str | None = None) -> None:
    """Drop all tables and re-run migrations. FOR TESTING ONLY."""
    path = db_path or DB_PATH
    with sqlite3.connect(path) as conn:
        tables = [r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() if r["name"] not in ("sqlite_sequence",)]
        for table in tables:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    run_migrations(path)
    logger.warning("Database reset: %s", path)
