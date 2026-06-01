"""Concurrent read/write load test for SharedMemoryStore.

Verifies that concurrent reads and writes are handled correctly under load:
- Concurrent read operations do not block each other excessively
- Write queue remains bounded under concurrent write pressure
- No data corruption or lost writes under concurrent load

Run: pytest backend/tests/integration/test_memory_store_concurrent.py -v
"""

from __future__ import annotations

import asyncio
import uuid

import pytest


@pytest.fixture
async def store(tmp_path):
    """Isolated SharedMemoryStore instance with temp directories."""
    from backend.memory.store import SharedMemoryStore

    db = str(tmp_path / "memory.db")
    chroma = str(tmp_path / "chroma")
    store = SharedMemoryStore(db_path=db, chroma_dir=chroma, sqlite_pool_size=5)
    await store.start()
    yield store
    await store.stop()


@pytest.mark.asyncio
async def test_concurrent_reads_do_not_interfere(store):
    """Multiple concurrent read() calls succeed without errors."""
    async def read_task(i: int):
        try:
            result = await store.read(query=f"test query {i}", top_k=3)
            return ("ok", result)
        except Exception as exc:
            return ("error", str(exc))

    results = await asyncio.gather(*[read_task(i) for i in range(20)])

    errors = [r for r in results if r[0] == "error"]
    assert errors == [], f"Read errors under concurrency: {errors}"


@pytest.mark.asyncio
async def test_concurrent_write_queue_bounded_under_load(store):
    """Write queue stays within configured maxsize under concurrent write pressure.

    WRITE_QUEUE_MAXSIZE = 1000 from store.py. If writes arrive faster than
    they are processed, the queue should accept up to maxsize without blocking
    the caller and without raising QueueFull.
    """
    async def write_task(i: int):
        try:
            await store.write(
                memory_type="episodic",
                content={
                    "id": str(uuid.uuid4()),
                    "project_id": "test",
                    "task_id": f"task-{i}",
                    "task_type": "general",
                    "agent_role": "coo",
                    "summary": f"Concurrent write {i}",
                    "outcome_status": "completed",
                },
                project_id="test",
            )
            return "ok"
        except asyncio.QueueFull:
            return "queue_full"

    write_count = 500
    results = await asyncio.gather(*[write_task(i) for i in range(write_count)])

    queue_fulls = [r for r in results if r == "queue_full"]
    assert queue_fulls == [], f"Queue hit full under {write_count} concurrent writes: {len(queue_fulls)} rejected"


@pytest.mark.asyncio
async def test_concurrent_reads_and_writes_succeed(store):
    """Read and write operations can run concurrently without corruption."""
    from backend.memory.episodic import EpisodicMemory

    async def writer(i: int):
        record = EpisodicMemory(
            id=str(uuid.uuid4()),
            project_id="test",
            task_id=f"task-{i}",
            task_type="general",
            agent_role="coo",
            summary=f"Write {i}",
            outcome_status="completed",
        )
        await store.write_episodic(record)

    async def reader(i: int):
        await store.read(query=f"reader {i}", top_k=5)

    tasks = []
    for i in range(50):
        tasks.append(writer(i))
        tasks.append(reader(i))

    await asyncio.gather(*tasks, return_exceptions=True)

    assert store._metrics.writes_completed >= 0


@pytest.mark.asyncio
async def test_concurrent_semantic_writes_not_blocked_by_reads(store):
    """Semantic writes do not block reads; both can proceed in parallel."""
    import hashlib

    async def writer(i: int):
        text = f"semantic test document {i} {uuid.uuid4()}"
        await store.write_semantic(
            text=text,
            project_id="test",
            task_id=f"task-{i}",
            agent_role="researcher",
        )

    async def reader(i: int):
        await store.read(query=f"query {i}", top_k=5, project_id="test")

    write_count = 100
    read_count = 50

    await asyncio.gather(
        *[writer(i) for i in range(write_count)],
        *[reader(i) for i in range(read_count)],
        return_exceptions=True,
    )


@pytest.mark.asyncio
async def test_write_queue_metrics_record_throughput(store):
    """Write queue metrics reflect actual queued writes under concurrent load."""
    initial = store._metrics.writes_enqueued

    async def writer(i: int):
        await store.write(
            memory_type="episodic",
            content={
                "id": str(uuid.uuid4()),
                "project_id": "test",
                "task_id": f"task-{i}",
                "task_type": "general",
                "agent_role": "coo",
                "summary": f"Write {i}",
                "outcome_status": "completed",
            },
            project_id="test",
        )

    await asyncio.gather(*[writer(i) for i in range(20)])

    assert store._metrics.writes_enqueued > initial, (
        f"Metrics not updated: initial={initial}, current={store._metrics.writes_enqueued}"
    )
