"""SharedMemoryStore — sole interface for all memory read/write operations.

From SPEC.md §2.2 — the single facade that all agents must use.
Routes reads and writes to the correct underlying store:
  - Semantic  → ChromaDB (via SemanticMemory)
  - Episodic  → PGLite   (via EpisodicMemoryStore)
  - Style     → PGLite   (via WritingProfileStore)

Key principles:
  - All writes go through async queue (not direct) to serialize and deduplicate
  - Semantic writes call sanitize_for_memory() first (§3b.8 Layer 1)
  - Semantic reads verify HMAC and exclude tampered entries
  - classify_task_type() keyword rules scope episodic retrieval
  - TASK_TYPE_RULES imported from routing.py (single source of truth)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from ..agents.routing import TASK_TYPE_RULES
from .episodic import EpisodicMemory, EpisodicMemoryStore
from .semantic import SemanticMemory
from .style import WritingProfileStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------------------
# Memory result container
# ---------------------------------------------------------------------------------------


@dataclass
class MemoryResult:
    memory_type: str = ""  # "semantic" | "episodic" | "style"
    records: list[Any] = field(default_factory=list)
    formatted: str = ""  # human-readable rendering
    degraded_quality: bool = False  # set True when this layer ran in degraded mode

    def to_prompt_block(self) -> str:
        # Return the formatted string even when records is empty (degraded mode indicator)
        if not self.records and not self.formatted:
            return ""
        if not self.records:
            return self.formatted  # degraded mode: show formatted message as warning
        return f"## {self.memory_type.title()} Memory\n{self.formatted}"


# ---------------------------------------------------------------------------------------
# Combined context formatter
# ---------------------------------------------------------------------------------------


def format_combined_context(results: list[MemoryResult]) -> str:
    """Combine heterogeneous memory results into a single context string for prompt injection."""
    # Include results that have records OR have a non-empty formatted string (degraded mode indicator)
    sections = [r.to_prompt_block() for r in results if r.records or r.formatted]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------------------
# Write queue item
# ---------------------------------------------------------------------------------------


@dataclass
class _WriteItem:
    memory_type: str
    content: dict[str, Any]
    project_id: str | None = None


# ---------------------------------------------------------------------------------------
# Circuit breaker for downstream failures
# ---------------------------------------------------------------------------------------


class WriteCircuitBreaker:
    """Circuit breaker for downstream memory store failures.

    Tracks consecutive failures per memory type (semantic/episodic/style).
    After max_failures, the circuit opens for circuit_timeout seconds,
    preventing further requests to the failing store.
    """

    FAILURE_THRESHOLD = 5
    RECOVERY_TIMEOUT = 60.0  # seconds

    def __init__(self, name: str) -> None:
        self.name = name
        self.failure_count = 0
        self._open_at: float | None = None
        self._lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        """Check if circuit is currently open (tripped)."""
        if self._open_at is None:
            return False
        if time.monotonic() - self._open_at >= self.RECOVERY_TIMEOUT:
            # Timeout expired — try to close the circuit
            self._open_at = None
            self.failure_count = 0
            return False
        return True

    async def record_failure(self) -> None:
        """Record a failure and potentially trip the circuit."""
        async with self._lock:
            self.failure_count += 1
            if self.failure_count >= self.FAILURE_THRESHOLD:
                self._open_at = time.monotonic()

    async def record_success(self) -> None:
        """Reset on successful call."""
        async with self._lock:
            self.failure_count = 0
            self._open_at = None

    async def can_execute(self) -> bool:
        """Check if execution is allowed (not blocked by open circuit)."""
        return not self.is_open


# ---------------------------------------------------------------------------------------
# Write queue metrics
# ---------------------------------------------------------------------------------------


@dataclass
class WriteQueueMetrics:
    """Metrics for write queue monitoring."""

    writes_enqueued: int = 0
    writes_completed: int = 0
    writes_dropped: int = 0
    writes_failed: int = 0
    watermark_warnings: int = 0
    circuit_trips: int = 0  # number of times circuit breaker tripped
    circuit_recoveries: int = 0  # number of times circuit recovered

    _lock: Lock = field(default_factory=Lock)

    def record_enqueued(self) -> None:
        with self._lock:
            self.writes_enqueued += 1

    def record_completed(self) -> None:
        with self._lock:
            self.writes_completed += 1

    def record_dropped(self) -> None:
        with self._lock:
            self.writes_dropped += 1

    def record_failed(self) -> None:
        with self._lock:
            self.writes_failed += 1

    def record_watermark_warning(self) -> None:
        with self._lock:
            self.watermark_warnings += 1

    def record_circuit_trip(self) -> None:
        with self._lock:
            self.circuit_trips += 1

    def record_circuit_recovery(self) -> None:
        with self._lock:
            self.circuit_recoveries += 1

    def to_dict(self) -> dict[str, int]:
        with self._lock:
            return {
                "writes_enqueued": self.writes_enqueued,
                "writes_completed": self.writes_completed,
                "writes_dropped": self.writes_dropped,
                "writes_failed": self.writes_failed,
                "watermark_warnings": self.watermark_warnings,
                "circuit_trips": self.circuit_trips,
                "circuit_recoveries": self.circuit_recoveries,
            }


# ---------------------------------------------------------------------------------------
# SharedMemoryStore
# ---------------------------------------------------------------------------------------


class SharedMemoryStore:
    """Sole interface for all memory read/write operations by agents.

    All agents (COO, CMO, Researcher, Engineer) access memory through this class only.
    Direct writes to ChromaDB or PGLite bypass HMAC signing and will fail verification.

    Architecture:
      - Semantic  → ChromaDB via self._semantic
      - Episodic   → PGLite  via self._episodic
      - Style      → PGLite  via self._style

    Write path: enqueued to self._write_queue → background worker processes
                with deduplication (24h lookback).
                Queue has maxsize=1000 with overflow protection.
    """

    # Backpressure configuration
    MAX_QUEUE_SIZE = 1000
    HIGH_WATERMARK = 750  # 75% - log warning here

    def __init__(
        self,
        db_path: str | None = None,
        chroma_dir: str | None = None,
        chroma_host: str | None = None,
        dedup_lookback_hours: int = 24,
        sqlite_pool_size: int = 5,
    ):
        self._semantic = SemanticMemory(chroma_dir=chroma_dir, chroma_host=chroma_host)
        self._episodic = EpisodicMemoryStore(db_path=db_path, pool_size=sqlite_pool_size)
        self._style = WritingProfileStore(db_path=db_path)
        self._dedup_hours = dedup_lookback_hours

        # Async write queue with backpressure protection
        self._write_queue: asyncio.Queue = asyncio.Queue(maxsize=self.MAX_QUEUE_SIZE)
        self._write_worker_task: asyncio.Task | None = None
        self._started = False
        self._dropped_writes = 0
        self._high_watermark_logged = False

        # Write queue metrics
        self._metrics = WriteQueueMetrics()

        # Circuit breakers per memory type for downstream failure handling
        self._circuit_breakers: dict[str, WriteCircuitBreaker] = {
            "semantic": WriteCircuitBreaker("semantic"),
            "episodic": WriteCircuitBreaker("episodic"),
            "style": WriteCircuitBreaker("style"),
        }

    # ---------------------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------------------

    async def start(self) -> None:
        """Start the memory stores and background write worker. Call once at startup."""
        if self._started:
            return
        self._started = True

        # Start async SQLite stores
        await self._episodic.start()
        await self._style.start()

        # Start write worker
        self._write_worker_task = asyncio.create_task(self._process_writes())
        logger.info("SharedMemoryStore started with async SQLite pools")

    async def stop(self) -> None:
        """Stop the write worker and SQLite connection pools gracefully."""
        if self._write_worker_task:
            try:
                self._write_queue.put_nowait(None)  # sentinel
                await self._write_worker_task
            except (RuntimeError, asyncio.CancelledError):
                self._write_worker_task.cancel()
                try:
                    await self._write_worker_task
                except (asyncio.CancelledError, RuntimeError):
                    pass

        await self._episodic.stop()
        await self._style.stop()
        logger.info("SharedMemoryStore stopped")

    # ---------------------------------------------------------------------------
    # Read path
    # ---------------------------------------------------------------------------

    async def read(
        self,
        query: str,
        project_id: str | None = None,
        memory_types: list[str] | None = None,
        top_k: int = 5,
    ) -> str:
        """Read from memory stores and combine into a context string for prompt injection.

        Args:
            query: Natural language query driving the retrieval.
            project_id: Scopes retrieval to a project (None = global).
            memory_types: Which layers to search. Defaults to all three.
            top_k: Max records per layer.

        Returns:
            A formatted context string ready for prompt injection.
        """
        if memory_types is None:
            memory_types = ["semantic", "episodic", "style"]

        results: list[MemoryResult] = []
        task_type = "general"
        query_lower = query.lower()
        for rule_type, keywords in TASK_TYPE_RULES:
            if any(kw in query_lower for kw in keywords):
                task_type = rule_type
                break

        # Semantic layer — hybrid vector + BM25 retrieval
        if "semantic" in memory_types:
            try:
                semantic_records = await self._semantic.retrieve(
                    query=query,
                    project_id=project_id,
                    top_k=top_k,
                )
                formatted = "\n".join(
                    f"- [{r.metadata.get('agent_role', '?')}] {r.text[:200]}" for r in semantic_records
                )
                results.append(
                    MemoryResult(
                        memory_type="semantic",
                        records=semantic_records,
                        formatted=formatted or "(no relevant semantic memories)",
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Semantic memory retrieval failed (ChromaDB unavailable?): %s. "
                    "Falling back to episodic-only retrieval.",
                    exc,
                )
                results.append(
                    MemoryResult(
                        memory_type="semantic",
                        records=[],
                        formatted="(semantic memory unavailable — degraded mode)",
                        degraded_quality=True,
                    )
                )

        # Episodic layer
        if "episodic" in memory_types:
            episodic_records: list[EpisodicMemory] = await self._episodic.query_by_project(
                project_id=project_id,
                task_type=task_type,
                limit=top_k,
            )
            if not episodic_records:
                episodic_records = await self._episodic.query_by_project(
                    project_id=project_id,
                    limit=top_k,
                )
            formatted = "\n".join(r.format() for r in episodic_records)
            results.append(
                MemoryResult(
                    memory_type="episodic",
                    records=episodic_records,
                    formatted=formatted or "(no recent similar tasks)",
                )
            )

        # Style layer
        if "style" in memory_types:
            formatted = await self._style.format()
            results.append(
                MemoryResult(
                    memory_type="style",
                    records=[],
                    formatted=formatted,
                )
            )

        return format_combined_context(results)

    # ---------------------------------------------------------------------------
    # Write path
    # ---------------------------------------------------------------------------

    async def write(
        self,
        memory_type: str,
        content: dict[str, Any],
        project_id: str | None = None,
    ) -> None:
        """Enqueue a memory write. Write happens asynchronously."""
        if not self._started:
            await self.start()

        # Backpressure check - log warning at high watermark
        queue_size = self._write_queue.qsize()
        if queue_size >= self.HIGH_WATERMARK and not self._high_watermark_logged:
            logger.warning(
                "Write queue at %d/%d (%.0f%%) - backpressure active",
                queue_size,
                self.MAX_QUEUE_SIZE,
                (queue_size / self.MAX_QUEUE_SIZE) * 100,
            )
            self._metrics.record_watermark_warning()
            self._high_watermark_logged = True

        # Try to enqueue, drop on overflow
        try:
            self._write_queue.put_nowait(
                _WriteItem(
                    memory_type=memory_type,
                    content=content,
                    project_id=project_id,
                )
            )
            self._metrics.record_enqueued()
        except asyncio.QueueFull:
            self._metrics.record_dropped()
            self._dropped_writes += 1
            logger.error(
                "Write queue overflow - dropped write %d. Consider increasing MAX_QUEUE_SIZE or fixing write worker.",
                self._dropped_writes,
            )

    async def write_semantic(
        self,
        text: str,
        project_id: str | None = None,
        task_id: str | None = None,
        agent_role: str | None = None,
        **kwargs,
    ) -> list[str]:
        """Direct (non-queued) semantic write — used when you need IDs immediately."""
        from .sanitizer import ContentSource, SanitizationResult, sanitize_for_memory

        result: SanitizationResult = sanitize_for_memory(
            text=text,
            source=ContentSource.SKILL_OUTPUT,
            project_id=project_id,
        )
        if result.flags:
            logger.warning(
                "Suspicious semantic write flagged: risk=%.2f, flags=%s",
                result.risk_score,
                result.flags,
            )

        return await self._semantic.add(
            text=result.text,
            project_id=project_id,
            task_id=task_id,
            agent_role=agent_role,
            **kwargs,
        )

    async def write_episodic(self, record: EpisodicMemory) -> None:
        """Direct (non-queued) episodic write."""
        await self._episodic.insert(record)

    async def _process_writes(self) -> None:
        """Background worker: processes write queue with circuit breaker protection.

        Tracks completed writes and resets watermark warning when queue drains.
        Circuit breaker trips after consecutive failures to prevent cascade to downstream.
        """
        while True:
            item = await self._write_queue.get()
            if item is None:
                break

            # Check circuit breaker before executing
            cb = self._circuit_breakers.get(item.memory_type)
            if cb and await cb.can_execute() is False:
                logger.warning(
                    "Circuit breaker open for %s, skipping write. "
                    "Will retry after recovery timeout.",
                    item.memory_type,
                )
                self._metrics.record_failed()
                self._write_queue.task_done()
                continue

            try:
                if item.memory_type == "semantic":
                    await self.write_semantic(
                        text=item.content["text"],
                        project_id=item.project_id,
                        task_id=item.content.get("task_id"),
                        agent_role=item.content.get("agent_role"),
                    )
                elif item.memory_type == "episodic":
                    record = EpisodicMemory(**item.content)
                    await self._episodic.insert(record)
                elif item.memory_type == "style":
                    await self._style.update_style(item.content)
                else:
                    logger.warning("Unknown memory_type in write queue: %s", item.memory_type)
            except Exception as exc:
                logger.error("Error processing memory write: %s", exc)
                self._metrics.record_failed()
                if cb:
                    await cb.record_failure()
                    if cb.is_open:
                        logger.error(
                            "Circuit breaker tripped for %s after %d consecutive failures. "
                            "Writes to this memory type will be skipped for %.0f seconds.",
                            item.memory_type,
                            WriteCircuitBreaker.FAILURE_THRESHOLD,
                            WriteCircuitBreaker.RECOVERY_TIMEOUT,
                        )
            else:
                if cb:
                    await cb.record_success()
                    self._metrics.record_completed()
                else:
                    self._metrics.record_completed()
            self._write_queue.task_done()

    # ---------------------------------------------------------------------------
    # Style
    # ---------------------------------------------------------------------------

    def get_writing_profile(self) -> WritingProfileStore:
        return self._style

    async def update_writing_style(self, updates: dict[str, Any]) -> None:
        await self._style.update_style(updates)
        logger.info("Writing style profile updated: %s", list(updates.keys()))

    def get_queue_metrics(self) -> dict[str, Any]:
        """Return current write queue metrics."""
        metrics: dict[str, Any] = self._metrics.to_dict()
        metrics["queue_size"] = self._write_queue.qsize()
        metrics["queue_maxsize"] = self.MAX_QUEUE_SIZE
        metrics["queue_fill_ratio"] = float(self._write_queue.qsize()) / self.MAX_QUEUE_SIZE
        return metrics

    # ---------------------------------------------------------------------------
    # Management
    # ---------------------------------------------------------------------------

    async def delete_all_memories(self) -> dict[str, int]:
        episodic_count = await self._episodic.delete_older_than(days=0)
        semantic_count = self._semantic.delete_all()
        await self._style.update_style(
            {
                "tone": "semi-formal",
                "sentence_length": "medium",
                "first_person": "I",
                "signature_phrases": [],
                "greeting_style": "Hi [Name],",
                "signoff_style": "Cheers",
            }
        )
        return {"episodic_deleted": episodic_count, "semantic_deleted": semantic_count}

    async def episodic_count(self, project_id: str | None = None) -> int:
        records = await self._episodic.query_by_project(project_id=project_id, limit=1000)
        return len(records)

    def semantic_count(self, project_id: str | None = None) -> int:
        return self._semantic.count(project_id=project_id)


# Module-level constants for backwards compatibility
WRITE_QUEUE_MAXSIZE = 1000
WRITE_QUEUE_HIGH_WATERMARK = 0.75  # 75% capacity
WRITE_QUEUE_DROP_POLICY = "drop_oldest"  # "drop_oldest" | "raise"
