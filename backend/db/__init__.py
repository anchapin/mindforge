"""Database health checks. From SPEC.md Section 5e.4."""

from __future__ import annotations

import logging
import os
import sqlite3

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "mindforge.db")


async def check_pglite() -> bool:
    """Check PGLite is reachable."""
    try:
        if not os.path.exists(DB_PATH):
            return False
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Exception as exc:
        logger.warning("PGLite health check failed: %s", exc)
        return False


async def check_chroma() -> bool:
    """Check ChromaDB is reachable."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:8000/api/v1/heartbeat")
            return resp.status_code == 200
    except Exception:
        return False


async def check_temporal() -> bool:
    """Check Temporal worker is reachable."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:8088/api/v1/cluster/health")
            return resp.status_code == 200
    except Exception:
        return False


async def check_ollama() -> bool:
    """Check Ollama is reachable."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def check_all() -> dict[str, bool]:
    results: dict[str, bool] = {"pglite": await check_pglite()}
    return results
