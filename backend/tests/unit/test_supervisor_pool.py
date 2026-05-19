
import os

# Set DATA_DIR before any imports that might trigger directory creation
os.environ["DATA_DIR"] = "/tmp/mindforge_test_data"

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from backend.agents.supervisor import SupervisorRunner, SupervisorRunnerPool
from backend.memory.store import SharedMemoryStore


@pytest.mark.asyncio
async def test_pool_initialization():
    """Test that the pool initializes the correct number of runners."""
    memory_store = MagicMock(spec=SharedMemoryStore)
    pool = SupervisorRunnerPool(size=3)

    with patch("backend.agents.supervisor.SupervisorRunner.create") as mock_create:
        # Mock create to return a mock runner
        mock_runner = MagicMock(spec=SupervisorRunner)
        mock_create.return_value = mock_runner

        await pool.initialize(memory_store)

        assert pool._initialized is True
        assert mock_create.call_count == 3
        assert pool._queue.qsize() == 3

@pytest.mark.asyncio
async def test_pool_acquire_release():
    """Test acquiring and releasing runners from the pool."""
    memory_store = MagicMock(spec=SharedMemoryStore)
    pool = SupervisorRunnerPool(size=2)

    # Pre-populate pool with mock runners
    runner1 = MagicMock(spec=SupervisorRunner)
    runner2 = MagicMock(spec=SupervisorRunner)

    with patch("backend.agents.supervisor.SupervisorRunner.create") as mock_create:
        mock_create.side_effect = [runner1, runner2]
        await pool.initialize(memory_store)

    # Acquire first
    a1 = await pool.acquire()
    assert a1 == runner1
    assert pool._queue.qsize() == 1

    # Acquire second
    a2 = await pool.acquire()
    assert a2 == runner2
    assert pool._queue.qsize() == 0

    # Release first
    await pool.release(a1)
    assert pool._queue.qsize() == 1

    # Release second
    await pool.release(a2)
    assert pool._queue.qsize() == 2

    # Re-acquire
    a3 = await pool.acquire()
    assert a3 == runner1 # Queue follows FIFO by default

@pytest.mark.asyncio
async def test_pool_blocks_when_empty():
    """Test that acquire blocks until a runner is released."""
    memory_store = MagicMock(spec=SharedMemoryStore)
    pool = SupervisorRunnerPool(size=1)

    runner1 = MagicMock(spec=SupervisorRunner)
    with patch("backend.agents.supervisor.SupervisorRunner.create", return_value=runner1):
        await pool.initialize(memory_store)

    # Acquire the only runner
    await pool.acquire()

    # Try to acquire another one with a timeout
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(pool.acquire(), timeout=0.1)

    # Release the runner in the background
    async def release_later():
        await asyncio.sleep(0.1)
        await pool.release(runner1)

    asyncio.create_task(release_later())

    # This should now succeed
    a2 = await asyncio.wait_for(pool.acquire(), timeout=0.5)
    assert a2 == runner1

@pytest.mark.asyncio
async def test_pool_size_configurable():
    """Test that pool size is configurable via environment variable."""
    with patch.dict(os.environ, {"SUPERVISOR_POOL_SIZE": "4"}):
        # Reset global pool to force re-creation
        import backend.agents.supervisor
        from backend.agents.supervisor import get_supervisor_pool
        backend.agents.supervisor._supervisor_pool = None

        pool = get_supervisor_pool()
        assert pool._size == 4

@pytest.mark.asyncio
async def test_pool_uninitialized_fallback():
    """Test fallback when acquire is called on uninitialized pool."""
    pool = SupervisorRunnerPool(size=2)
    assert pool._initialized is False

    mock_runner = MagicMock(spec=SupervisorRunner)
    with (
        patch("backend.agents.supervisor.SupervisorRunner.create", return_value=mock_runner) as mock_create,
        # We need to mock get_memory_store too because acquire calls it
        patch("backend.api.deps.get_memory_store") as mock_get_mem,
    ):
        a = await pool.acquire()
        assert a == mock_runner
        mock_create.assert_called_once()
