"""MindForge FastAPI entry point."""

import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import (
    integrations,
    memories,
    onboarding,
    preferences,
    skills,
    tasks,
    usage,
    webhooks,
)
from backend.api.websocket import ws_manager
from backend.db.migrate import run_migrations
from backend.llm.router import LLM_ROUTER
from backend.scheduler.temporal_app import TemporalClient
from backend.tools.registry import register_all_tools

logger = structlog.get_logger()

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", version=os.getenv("MINDFORGE_VERSION", "0.1.0-alpha"))

    # Run migrations
    try:
        run_migrations()
    except Exception as exc:
        logger.warning("migration_failed", exc=str(exc))

    # Initialize LLM router
    try:
        await LLM_ROUTER.initialize()
    except Exception as exc:
        logger.warning("llm_router_init_failed", exc=str(exc))

    # Register all built-in tools so the integrations API can probe them
    # and skill executors can resolve names like "stripe_api" / "email_send".
    # Without this every POST /api/integrations/{id}/test returns
    # "No tool 'X' registered" — the tool registry is empty at runtime
    # because nothing else in the app calls register_all_tools() (#42-#44 P1).
    try:
        register_all_tools()
    except Exception as exc:
        logger.warning("tool_registry_init_failed", exc=str(exc))

    # Initialize Temporal (Phase 3 — gated by ENABLE_TEMPORAL env var; stays in
    # stub mode when disabled so the rest of the API still serves requests).
    try:
        app.state.temporal = TemporalClient()
        await app.state.temporal.start()
    except Exception as exc:
        logger.warning("temporal_client_init_failed", exc=str(exc))

    yield

    logger.info("shutdown_initiated")
    if hasattr(app.state, "temporal"):
        await app.state.temporal.shutdown()
    logger.info("shutdown_complete")


app = FastAPI(
    title="MindForge API",
    version=os.getenv("MINDFORGE_VERSION", "0.1.0-alpha"),
    lifespan=lifespan,
)

# CORS -- dashboard connects from same origin only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount REST routes
app.include_router(tasks.router)
app.include_router(memories.router)
app.include_router(skills.router)
app.include_router(integrations.router)
app.include_router(preferences.router)
app.include_router(onboarding.router)
app.include_router(usage.router)
app.include_router(webhooks.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, task_id: str | None = None):
    """WebSocket endpoint for real-time dashboard updates."""
    await ws_manager.connect(websocket, task_id=task_id)
    try:
        while True:
            # Keep connection alive; receive any incoming messages from dashboard
            data = await websocket.receive_text()
            # Dashboard -> agent messages (e.g., approval actions)
            await ws_manager.broadcast({"type": "dashboard_message", "text": data})
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(websocket, task_id=task_id)


@app.get("/health")
async def health():
    return {"status": "ok", "version": os.getenv("MINDFORGE_VERSION", "0.1.0-alpha")}


@app.get("/ready")
async def ready():
    from backend.db import check_chroma, check_pglite

    pglite_ok = await check_pglite()
    chroma_ok = await check_chroma()
    return {
        "status": "ready" if (pglite_ok and chroma_ok) else "not_ready",
        "checks": {"pglite": pglite_ok, "chroma": chroma_ok},
    }
