"""FastAPI dependency injection.

Provides shared resources: database connections, memory store, WebSocket manager.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import sqlite3

from ..memory.store import SharedMemoryStore
from ..api.websocket import ws_manager, WSConnectionManager

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
