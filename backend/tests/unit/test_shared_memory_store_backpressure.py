import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.memory.store import WRITE_QUEUE_HIGH_WATERMARK, WRITE_QUEUE_MAXSIZE, SharedMemoryStore


@pytest.mark.asyncio
async def test_write_queue_backpressure_drop_oldest():
    # Setup store with small maxsize for testing if we wanted,
    # but we'll use the constant to match reality.
    # Actually, the constants are hardcoded in the module.

    with patch("backend.memory.semantic.chromadb.HttpClient") as mock_chroma:
        mock_client = mock_chroma.return_value
        mock_client.get_or_create_collection = MagicMock()
        store = SharedMemoryStore(db_path=":memory:", chroma_dir=None)

    # We don't start the store so the worker doesn't drain the queue
    store._started = True # Pretend it's started so write() doesn't call start()

    # 1. Fill the queue up to 75% to trigger watermark
    # Need 750 items in queue so the 751st call triggers the warning
    watermark_limit = int(WRITE_QUEUE_MAXSIZE * WRITE_QUEUE_HIGH_WATERMARK)
    for i in range(watermark_limit + 1):
        await store.write("semantic", {"text": f"item {i}"})

    metrics = store.get_queue_metrics()
    assert metrics["writes_enqueued"] == watermark_limit + 1
    assert metrics["watermark_warnings"] == 1

    # 2. Fill the queue to the max
    for i in range(watermark_limit + 1, WRITE_QUEUE_MAXSIZE):
        await store.write("semantic", {"text": f"item {i}"})

    metrics = store.get_queue_metrics()
    assert metrics["queue_size"] == WRITE_QUEUE_MAXSIZE
    assert metrics["writes_dropped"] == 0

    # 3. Push one more item — should trigger drop_oldest
    await store.write("semantic", {"text": "overflow item"})

    metrics = store.get_queue_metrics()
    assert metrics["queue_size"] == WRITE_QUEUE_MAXSIZE
    assert metrics["writes_dropped"] == 1
    assert metrics["writes_enqueued"] == WRITE_QUEUE_MAXSIZE + 1

    # Verify we can still read from the queue and it has the right number of items
    assert store._write_queue.qsize() == WRITE_QUEUE_MAXSIZE

@pytest.mark.asyncio
async def test_write_queue_backpressure_raise_policy():
    from backend.memory import store as store_module

    with patch.object(store_module, "WRITE_QUEUE_DROP_POLICY", "raise"):
        store = SharedMemoryStore(db_path=":memory:", chroma_dir=None)
        store._started = True

        # Fill the queue
        for i in range(WRITE_QUEUE_MAXSIZE):
            await store.write("semantic", {"text": f"item {i}"})

        # Push one more — should raise RuntimeError
        with pytest.raises(RuntimeError, match="Write queue full"):
            await store.write("semantic", {"text": "overflow item"})

        metrics = store.get_queue_metrics()
        assert metrics["queue_size"] == WRITE_QUEUE_MAXSIZE
        assert metrics["writes_dropped"] == 0

@pytest.mark.asyncio
async def test_write_queue_watermark_reset():
    with patch("backend.memory.semantic.chromadb.HttpClient") as mock_chroma:
        mock_client = mock_chroma.return_value
        mock_client.get_or_create_collection = MagicMock()
        store = SharedMemoryStore(db_path=":memory:", chroma_dir=None)
        store._started = True

    watermark_limit = int(WRITE_QUEUE_MAXSIZE * WRITE_QUEUE_HIGH_WATERMARK)

    # Trigger watermark
    for i in range(watermark_limit + 1):
        await store.write("semantic", {"text": f"item {i}"})

    assert store._watermark_logged is True

    # Drain one item
    item = await store._write_queue.get()
    store._write_queue.task_done()

    # Worker would normally do this, let's simulate the check in _process_writes
    # Actually the reset logic is IN _process_writes.
    # Since we are not running _process_writes in this test,
    # we have to manually trigger the logic or let the worker run.

    # Let's try to let the worker run but mock the actual processing to be slow
    store._started = False

    async def slow_write(*args, **kwargs):
        await asyncio.sleep(0.01)
        return []

    with patch.object(store, "write_semantic", side_effect=slow_write):
        await store.start()

        # Fill it up
        for i in range(watermark_limit + 1):
            await store.write("semantic", {"text": f"item {i}"})

        assert store._metrics.watermark_warnings >= 1

        # Wait for it to drain below threshold
        # Threshold is < 750 (so 749)
        while store._write_queue.qsize() >= watermark_limit:
            await asyncio.sleep(0.01)

        # Wait for worker to finish one more loop to trigger reset
        await asyncio.sleep(0.1)

        # Watermark should be reset
        assert store._watermark_logged is False

        # Trigger it again
        for i in range(watermark_limit + 1):
            await store.write("semantic", {"text": f"again {i}"})

        assert store._metrics.watermark_warnings >= 2

        assert store._metrics.watermark_warnings >= 2

        await store.stop()
