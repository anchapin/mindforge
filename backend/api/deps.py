"""FastAPI dependency injection.

Provides shared resources: database connections, memory store, WebSocket manager.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ..api.websocket import WSConnectionManager, ws_manager
from ..memory.store import SharedMemoryStore

DATA_DIR = os.getenv("DATA_DIR", "/app/data")
DB_PATH = os.path.join(DATA_DIR, "mindforge.db")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma")

os.makedirs(DATA_DIR, exist_ok=True)

_memory_store: SharedMemoryStore | None = None


def get_memory_store() -> SharedMemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = SharedMemoryStore(
            db_path=DB_PATH,
            chroma_dir=CHROMA_DIR,
        )
    return _memory_store


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


@asynccontextmanager
async def get_db_context() -> AsyncIterator[sqlite3.Connection]:
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


def get_ws_manager() -> WSConnectionManager:
    return ws_manager


# ---------------------------------------------------------------------------------------
# ---------------------------------------------------------------------------------------
# FastAPI route dependencies
# ---------------------------------------------------------------------------------------


async def db_dep() -> AsyncIterator[sqlite3.Connection]:
    """FastAPI dependency that provides a SQLite database connection.

    Yields a connection from get_db() and closes it when done.
    """
    conn = get_db()
    try:
        yield conn
    finally:
        conn.close()


async def memory_dep() -> SharedMemoryStore:
    """FastAPI dependency that provides the shared memory store singleton."""
    return get_memory_store()
