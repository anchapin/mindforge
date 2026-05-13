"""Temporal workflow client. Phase 3+ proactive execution. Phase 1 stub."""

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


class TemporalClient:
    def __init__(self):
        self._started = False
        logger.warning("TemporalClient: Phase 3+ feature -- running in stub mode")

    async def shutdown(self) -> None:
        logger.info("TemporalClient shutdown")

    async def start_workflow(self, workflow_name: str, **kwargs) -> None:
        logger.info("Temporal workflow stub: %s (not started -- Phase 3)", workflow_name)
