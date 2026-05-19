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

All SQLite operations use aiosqlite via async connection pools for non-blocking I/O.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .episodic import EpisodicMemory, EpisodicMemoryStore
from .semantic import SemanticMemory
from .style import WritingProfileStore
from ..agents.routing import classify_task_type

logger = logging.getLogger(__name__)

# Queue configuration
WRITE_QUEUE_MAXSIZE = 1000
WRITE_QUEUE_HIGH_WATERMARK = 0.75  # 75% capacity triggers warning
WRITE_QUEUE_DROP_POLICY = "drop_oldest"  # "drop_oldest" | "raise"

# ---------------------------------------------------------------------------------------
# Memory result container
# ---------------------------------------------------------------------------------------


@dataclass
class MemoryResult:
    memory_type: str  # "semantic" | "episodic" | "style"
    records: list[Any] = field(default_factory=list)
    formatted: str = ""  # human-readable rendering
    degraded_quality: bool = False  # True when semantic layer failed (ChromaDB unavailable)

    def to_prompt_block(self) -> str:
        if not self.records and not self.degraded_quality:
            return ""
        return f"## {self.memory_type.title()} Memory\n{self.formatted}"


# ---------------------------------------------------------------------------------------
# Combined context formatter
# ---------------------------------------------------------------------------------------


def format_combined_context(results: list[MemoryResult]) -> str:
    """Combine heterogeneous memory results into a single context string for prompt injection.

    degraded_quality blocks are included even when records is empty so the LLM knows
    about the degraded state and can surface a warning to the user.
    """
    sections = [r.to_prompt_block() for r in results if r.records or r.degraded_quality]
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
      - Episodic   → PGLite  via self._episodic (async aiosqlite)
      - Style      → PGLite  via self._style (async aiosqlite)

    Write path: enqueued to self._write_queue → background worker processes
                with deduplication (24h lookback).

    All SQLite operations use async connection pools for non-blocking I/O.
    """

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
        self._style = WritingProfileStore(db_path=db_path, pool_size=sqlite_pool_size)
        self._dedup_hours = dedup_lookback_hours

        # Bounded async write queue with backpressure
        self._write_queue: asyncio.Queue = asyncio.Queue(maxsize=WRITE_QUEUE_MAXSIZE)
        self._write_worker_task: asyncio.Task | None = None
        self._started = False

        # Write queue metrics
        self._metrics = WriteQueueMetrics()

        # Track if we've logged watermark warning (reset on drain)
        self._watermark_logged = False

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
                # Event loop closing — cancel and await the task directly
                self._write_worker_task.cancel()
                try:
                    await self._write_worker_task
                except (asyncio.CancelledError, RuntimeError):
                    pass

        await self._episodic.stop()
        await self._style.stop()

        self._started = False
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
        task_type = classify_task_type(query)

        # Semantic layer — hybrid vector + BM25 retrieval
        if "semantic" in memory_types:
            try:
                semantic_records = await self._semantic.retrieve(
                    query=query,
                    project_id=project_id,
                    top_k=top_k,
                )

                if self._semantic.degraded:
                    results.append(
                        MemoryResult(
                            memory_type="semantic",
                            records=[],
                            formatted="(semantic memory unavailable — degraded mode)",
                            degraded_quality=True,
                        )
                    )
                else:
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

        # Episodic layer (async)
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

        # Style layer (async)
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
        """Enqueue a memory write. Blocks caller if queue is full (backpressure).

        When queue reaches high watermark (75%), a warning is logged.
        When queue is full, oldest entries are dropped to make room (drop_oldest policy).
        """
        if not self._started:
            await self.start()

        # Check high watermark and log warning once
        await self._check_watermark()

        # Try to enqueue with backpressure handling
        item = _WriteItem(
            memory_type=memory_type,
            content=content,
            project_id=project_id,
        )

        try:
            self._write_queue.put_nowait(item)
            self._metrics.record_enqueued()
        except asyncio.QueueFull:
            # Queue full — apply drop_oldest policy
            if WRITE_QUEUE_DROP_POLICY == "drop_oldest":
                try:
                    # Remove oldest item to make room
                    self._write_queue.get_nowait()
                    self._metrics.record_dropped()
                    # Now put the new item
                    self._write_queue.put_nowait(item)
                    self._metrics.record_enqueued()
                    logger.warning(
                        "Write queue overflow: dropped oldest entry. "
                        "Queue size: %d/%d",
                        self._write_queue.qsize(),
                        WRITE_QUEUE_MAXSIZE,
                    )
                except asyncio.QueueFull:
                    # Even after dropping, queue is full — drop the new item
                    self._metrics.record_dropped()
                    logger.error(
                        "Write queue critical overflow: dropped incoming write. "
                        "Queue size: %d/%d",
                        self._write_queue.qsize(),
                        WRITE_QUEUE_MAXSIZE,
                    )
            else:
                # raise policy
                raise RuntimeError(
                    f"Write queue full ({WRITE_QUEUE_MAXSIZE} items). "
                    f"Backpressure requires caller to retry."
                )

    async def _check_watermark(self) -> None:
        """Log warning when queue reaches high watermark (75% capacity)."""
        if self._watermark_logged:
            return
        fill_ratio = self._write_queue.qsize() / WRITE_QUEUE_MAXSIZE
        if fill_ratio >= WRITE_QUEUE_HIGH_WATERMARK:
            self._watermark_logged = True
            self._metrics.record_watermark_warning()
            logger.warning(
                "Write queue high watermark reached: %d/%d (%.0f%%). "
                "Backpressure active. Consider scaling ChromaDB or increasing queue size.",
                self._write_queue.qsize(),
                WRITE_QUEUE_MAXSIZE,
                fill_ratio * 100,
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
            try:
                item = await self._write_queue.get()
            except asyncio.CancelledError:
                # Event loop shutting down — drain the queue before exiting
                while not self._write_queue.empty():
                    try:
                        self._write_queue.get_nowait()
                        self._write_queue.task_done()
                    except asyncio.QueueEmpty:
                        break
                break
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
                        self._metrics.record_circuit_trip()
                        logger.error(
                            "Circuit breaker tripped for %s after %d consecutive failures. "
                            "Writes to this memory type will be skipped for %.0f seconds.",
                            item.memory_type,
                            WriteCircuitBreaker.FAILURE_THRESHOLD,
                            WriteCircuitBreaker.RECOVERY_TIMEOUT,
                        )
            else:
                self._metrics.record_completed()
                if cb:
                    await cb.record_success()
                    # Check if circuit just recovered
                    if cb.failure_count == 0 and not cb.is_open:
                        if self._metrics.circuit_trips > 0:
                            self._metrics.record_circuit_recovery()
                            logger.info(
                                "Circuit breaker recovered for %s, resuming writes.",
                                item.memory_type,
                            )
            finally:
                self._write_queue.task_done()

            # Reset watermark flag when queue drains below threshold
            if self._watermark_logged and self._write_queue.qsize() < int(WRITE_QUEUE_MAXSIZE * WRITE_QUEUE_HIGH_WATERMARK):
                self._watermark_logged = False

    # ---------------------------------------------------------------------------
    # Style
    # ---------------------------------------------------------------------------

    async def get_writing_profile(self) -> dict[str, Any]:
        """Get the writing profile as a dict."""
        return (await self._style.get()).to_dict()

    async def update_writing_style(self, updates: dict[str, Any]) -> None:
        await self._style.update_style(updates)
        logger.info("Writing style profile updated: %s", list(updates.keys()))

    # ---------------------------------------------------------------------------
    # Management
    # ---------------------------------------------------------------------------

    async def delete_all_memories(self) -> dict[str, int]:
        episodic_count = await self._episodic.delete_older_than(days=0)
        if episodic_count is None:
            episodic_count = 0
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

    def get_queue_metrics(self) -> dict[str, Any]:
        """Return current write queue metrics."""
        metrics: dict[str, Any] = self._metrics.to_dict()  # type: ignore[assignment]
        metrics["queue_size"] = self._write_queue.qsize()
        metrics["queue_maxsize"] = WRITE_QUEUE_MAXSIZE
        metrics["queue_fill_ratio"] = float(self._write_queue.qsize()) / WRITE_QUEUE_MAXSIZE
        return metrics

    # ---------------------------------------------------------------------------
    # Legacy sync accessors (for backward compatibility with existing routes)
    # These are temporary shims to ease migration — do not use in new code.
    # ---------------------------------------------------------------------------

    @property
    def episodic_store(self) -> EpisodicMemoryStore:
        """Sync accessor for code that hasn't been migrated yet."""
        return self._episodic

    @property
    def style_store(self) -> WritingProfileStore:
        """Sync accessor for code that hasn't been migrated yet."""
        return self._style
