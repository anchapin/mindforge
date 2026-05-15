"""MindForge FastAPI entry point."""

import json
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import (
    integrations,
    memories,
    oauth,
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

    app.state.components = {}

    # Run migrations
    try:
        run_migrations()
        app.state.components["db"] = "ok"
    except Exception as exc:
        logger.error("migration_failed", exc=str(exc))
        app.state.components["db"] = "failed"

    # Initialize LLM router — FATAL: backend cannot serve requests without LLM
    try:
        await LLM_ROUTER.initialize()
        app.state.components["llm_router"] = "ok"
    except Exception as exc:
        logger.critical("llm_router_init_failed", exc=str(exc))
        app.state.components["llm_router"] = "failed"
        raise  # FATAL — do not continue

    # Register all built-in tools so the integrations API can probe them
    # and skill executors can resolve names like "stripe_api" / "email_send".
    # Without this every POST /api/integrations/{id}/test returns
    # "No tool 'X' registered" — the tool registry is empty at runtime
    # because nothing else in the app calls register_all_tools() (#42-#44 P1).
    try:
        register_all_tools()
        app.state.components["tool_registry"] = "ok"
    except Exception as exc:
        logger.warning("tool_registry_init_failed", exc=str(exc))
        app.state.components["tool_registry"] = "failed"
        # RECOVERABLE — continue without auto-registration

    # Initialize Temporal (Phase 3 — gated by ENABLE_TEMPORAL env var; stays in
    # stub mode when disabled so the rest of the API still serves requests).
    try:
        app.state.temporal = TemporalClient()
        await app.state.temporal.start()
        app.state.components["temporal"] = "ok"
    except Exception as exc:
        logger.warning("temporal_client_init_failed", exc=str(exc))
        app.state.components["temporal"] = "failed"
        # RECOVERABLE — continue without Temporal

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
app.include_router(oauth.router)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, task_id: str | None = None):
    """WebSocket endpoint for real-time dashboard updates."""
    await ws_manager.connect(websocket, task_id=task_id)
    try:
        while True:
            # Keep connection alive; receive any incoming messages from dashboard
            data = await websocket.receive_text()
            try:
                parsed = json.loads(data)
            except Exception:
                continue  # ignore malformed inbound frames
            # Handle client-side commands (subscribe for replay, ping for heartbeat)
            await ws_manager.handle_message(websocket, task_id=task_id, data=parsed)
    except Exception:
        pass
    finally:
        await ws_manager.disconnect(websocket, task_id=task_id)


@app.get("/health")
async def health():
    return {"status": "ok", "version": os.getenv("MINDFORGE_VERSION", "0.1.0-alpha")}


@app.get("/health/detail")
async def health_detail():
    """Component-level health — distinguishes fatal from recoverable failures.

    RECOVERABLE failures (status "degraded"): tool_registry, temporal, db
    FATAL failures (status "failed"): llm_router
    """
    from backend.db import check_chroma, check_pglite

    components = getattr(app.state, "components", {})
    pglite_ok = await check_pglite()
    chroma_ok = await check_chroma()
    components = dict(components)
    components["pglite"] = "ok" if pglite_ok else "failed"
    components["chroma"] = "ok" if chroma_ok else "failed"

    # Determine overall status
    if components.get("llm_router") == "failed":
        overall = "failed"
    elif any(v == "failed" for v in components.values()):
        overall = "degraded"
    else:
        overall = "ok"

    return {"status": overall, "components": components, "version": os.getenv("MINDFORGE_VERSION", "0.1.0-alpha")}


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint (#52, SPEC §5.5).

    Renders the module-private CollectorRegistry from
    ``backend.observability.metrics`` in the canonical text exposition
    format. Side-effect free.
    """
    from starlette.responses import Response

    from backend.observability.metrics import METRICS_CONTENT_TYPE, get_metrics_text

    return Response(content=get_metrics_text(), media_type=METRICS_CONTENT_TYPE)


@app.get("/ready")
async def ready():
    from backend.db import check_chroma, check_pglite

    pglite_ok = await check_pglite()
    chroma_ok = await check_chroma()
    return {
        "status": "ready" if (pglite_ok and chroma_ok) else "not_ready",
        "checks": {"pglite": pglite_ok, "chroma": chroma_ok},
    }
