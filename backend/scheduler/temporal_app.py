"""Temporal workflow client — proactive execution engine (SPEC §5.3).

Phase 3 feature, gated behind ENABLE_TEMPORAL=true so the rest of the platform
keeps running when the broker is not deployed (AGENTS.md rule #6: phase scope).

Behavior:
    ENABLE_TEMPORAL=false (default)  → stub mode: every method is a no-op log
                                       so backend startup, tests, and the API
                                       work without a Temporal broker.
    ENABLE_TEMPORAL=true             → real mode: connect to TEMPORAL_HOST,
                                       start a worker registering all known
                                       workflows + activities, and proxy
                                       start_workflow to the SDK client.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TASK_QUEUE = "mindforge-proactive"
DEFAULT_NAMESPACE = "default"


def _is_enabled() -> bool:
    """Read ENABLE_TEMPORAL env var (default false) — checked at __init__ time."""
    return os.getenv("ENABLE_TEMPORAL", "false").lower() in ("1", "true", "yes", "on")


class TemporalClient:
    """Minimal facade over the temporalio SDK.

    Use the same instance from FastAPI app.state.temporal across the request
    lifecycle. The constructor never raises: a broker that cannot be reached
    leaves the instance in stub mode so the API still serves requests.
    """

    def __init__(self, *, host: str | None = None, namespace: str = DEFAULT_NAMESPACE) -> None:
        self.host = host or os.getenv("TEMPORAL_HOST", "temporal:7233")
        self.namespace = namespace
        self.enabled = _is_enabled()
        self._client: Any | None = None
        self._worker: Any | None = None
        self._worker_task: asyncio.Task | None = None

        if not self.enabled:
            logger.info(
                "TemporalClient: ENABLE_TEMPORAL=false — running in stub mode "
                "(set ENABLE_TEMPORAL=true and start the temporal compose profile to activate)"
            )

    async def start(self) -> None:
        """Connect to the broker and start the worker. No-op in stub mode.

        Errors are logged and swallowed: a missing broker must not crash backend
        startup. Caller can inspect self.enabled and self._client to verify.
        """
        if not self.enabled:
            return

        try:
            from temporalio.client import Client
            from temporalio.worker import Worker

            from .workflows import ALL_ACTIVITIES, ALL_WORKFLOWS

            self._client = await Client.connect(self.host, namespace=self.namespace)
            self._worker = Worker(
                self._client,
                task_queue=DEFAULT_TASK_QUEUE,
                workflows=list(ALL_WORKFLOWS),
                activities=list(ALL_ACTIVITIES),
            )
            self._worker_task = asyncio.create_task(self._worker.run())

            # Install recurring schedules (#57 part B). Failures are logged
            # and swallowed so a misconfigured schedule never blocks startup.
            try:
                from .workflows.oauth_refresh import ensure_oauth_refresh_schedule

                await ensure_oauth_refresh_schedule(self)
            except Exception as exc:  # pragma: no cover - defence-in-depth
                logger.warning(
                    "TemporalClient: schedule install error -- continuing (%s)",
                    exc,
                )

            logger.info(
                "TemporalClient: connected to %s namespace=%s queue=%s",
                self.host,
                self.namespace,
                DEFAULT_TASK_QUEUE,
            )
        except Exception as exc:  # pragma: no cover - exercised only with a broker
            logger.warning(
                "TemporalClient: failed to connect to %s — staying in stub mode (%s)",
                self.host,
                exc,
            )
            self._client = None
            self._worker = None
            self._worker_task = None

    async def shutdown(self) -> None:
        """Stop the worker and close the client. Safe to call in stub mode."""
        if self._worker is not None:
            try:
                await self._worker.shutdown()
            except Exception as exc:  # pragma: no cover
                logger.warning("TemporalClient.shutdown worker error: %s", exc)
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):
                pass
        # The temporalio Client doesn't currently expose an explicit close().
        self._client = None
        self._worker = None
        self._worker_task = None
        logger.info("TemporalClient shutdown")

    async def start_workflow(
        self,
        workflow: Any,
        *args: Any,
        id: str,
        task_queue: str = DEFAULT_TASK_QUEUE,
        **kwargs: Any,
    ) -> Any:
        """Start a workflow execution. No-op log in stub mode.

        Returns the temporalio WorkflowHandle in real mode, None in stub mode.
        """
        if self._client is None:
            logger.info(
                "Temporal workflow stub: %s id=%s (ENABLE_TEMPORAL=%s)",
                getattr(workflow, "__name__", workflow),
                id,
                self.enabled,
            )
            return None

        return await self._client.start_workflow(
            workflow,
            *args,
            id=id,
            task_queue=task_queue,
            **kwargs,
        )
