"""Database health checks. From SPEC.md Section 5e.4.

All service URLs honor the same environment variables that the rest of the
backend uses (CHROMA_HOST, TEMPORAL_HOST, OLLAMA_BASE_URL). Without this,
`/ready` reports services as unhealthy whenever they live anywhere other
than `127.0.0.1`, which is always the case under docker compose.
"""

from __future__ import annotations

import logging
import os
import sqlite3

import httpx

logger = logging.getLogger(__name__)

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "mindforge.db")

# Health-check timeout (seconds). Short on purpose: /ready must not block.
_HEALTH_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT_SECONDS", "5"))


def _chroma_heartbeat_url() -> str:
    base = os.getenv("CHROMA_HOST", "http://127.0.0.1:8000").rstrip("/")
    return f"{base}/api/v1/heartbeat"


def _temporal_health_url() -> str:
    """Temporal cluster health is exposed on the UI sidecar (8088), not 7233 (gRPC).

    TEMPORAL_HOST in this repo is the gRPC frontend (e.g., `temporal:7233`); the
    cluster-health REST endpoint is served by the temporal-ui container on port
    8088. We accept either an explicit override (TEMPORAL_HEALTH_URL) or fall
    back to a sane default.
    """
    explicit = os.getenv("TEMPORAL_HEALTH_URL")
    if explicit:
        return explicit.rstrip("/") + "/api/v1/cluster/health"
    # Best-effort default that matches compose.yaml `temporal-ui` service
    return "http://127.0.0.1:8088/api/v1/cluster/health"


def _ollama_tags_url() -> str:
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    return f"{base}/api/tags"


async def check_pglite() -> bool:
    """Check PGLite (SQLite) database is reachable."""
    try:
        if not os.path.exists(DB_PATH):
            return False
        conn = sqlite3.connect(DB_PATH, timeout=5)
        try:
            conn.execute("SELECT 1").fetchone()
        finally:
            conn.close()
        return True
    except Exception:
        logger.warning("PGLite health check failed", exc_info=True)
        return False


async def check_chroma() -> bool:
    """Check ChromaDB heartbeat endpoint at $CHROMA_HOST."""
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            resp = await client.get(_chroma_heartbeat_url())
            return resp.status_code == 200
    except Exception:
        logger.debug("Chroma health check failed", exc_info=True)
        return False


async def check_temporal() -> bool:
    """Check Temporal cluster-health endpoint."""
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            resp = await client.get(_temporal_health_url())
            return resp.status_code == 200
    except Exception:
        logger.debug("Temporal health check failed", exc_info=True)
        return False


async def check_ollama() -> bool:
    """Check Ollama tags endpoint at $OLLAMA_BASE_URL."""
    try:
        async with httpx.AsyncClient(timeout=_HEALTH_TIMEOUT) as client:
            resp = await client.get(_ollama_tags_url())
            return resp.status_code == 200
    except Exception:
        logger.debug("Ollama health check failed", exc_info=True)
        return False



async def check_all() -> dict[str, bool]:
    results: dict[str, bool] = {
        "pglite": await check_pglite(),
        "chroma": await check_chroma(),
        "temporal": await check_temporal(),
    }
    return results
