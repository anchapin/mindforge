"""Writing style profile CRUD (async).

From SPEC.md §2.2 — Writing Style Memory.
Singleton WritingProfile stored in PGLite. Updated on explicit user request
or extracted from approved drafts via LLM.

Uses aiosqlite for non-blocking async I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------------------


class AsyncSQLitePool:
    """Async connection pool for SQLite using aiosqlite.

    Maintains a pool of connections to avoid the overhead of creating
    new connections for each operation.
    """

    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=pool_size)
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Initialize the connection pool."""
        if self._started:
            return
        async with self._lock:
            if self._started:
                return
            for _ in range(self.pool_size):
                conn = await _ai_sqlite_connect(self.db_path)
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA busy_timeout=5000")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await self._pool.put(conn)
            self._started = True
            logger.info("AsyncSQLitePool started with %d connections", self.pool_size)

    async def stop(self) -> None:
        """Close all connections in the pool."""
        if not self._started:
            return
        async with self._lock:
            if not self._started:
                return
            while not self._pool.empty():
                try:
                    conn = self._pool.get_nowait()
                    await conn.close()
                except asyncio.QueueEmpty:
                    break
            self._started = False
            logger.info("AsyncSQLitePool stopped")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[Any]:
        """Acquire a connection from the pool."""
        if not self._started:
            await self.start()
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def execute(self, query: str, params: tuple = ()) -> list[dict]:
        """Execute a query and return all rows as dicts."""
        async with self.acquire() as conn:
            conn.row_factory = _dict_row_factory
            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()
            return rows

    async def execute_one(self, query: str, params: tuple = ()) -> dict | None:
        """Execute a query and return a single row as dict."""
        async with self.acquire() as conn:
            conn.row_factory = _dict_row_factory
            cursor = await conn.execute(query, params)
            row = await cursor.fetchone()
            return row if row else None

    async def execute_write(self, query: str, params: tuple = ()) -> int:
        """Execute a write query and return rowcount."""
        async with self.acquire() as conn:
            cursor = await conn.execute(query, params)
            await conn.commit()
            return cursor.rowcount


# aiosqlite types
ai_sqlite_Connection = Any  # aiosqlite.Connection


async def _ai_sqlite_connect(db_path: str) -> ai_sqlite_Connection:
    """Connect to SQLite using aiosqlite for async operations."""
    import aiosqlite
    return await aiosqlite.connect(db_path)


def _dict_row_factory(cursor: Any, row: tuple) -> dict:
    """Convert a sqlite row to a dict using column names."""
    # aiosqlite uses cursor.column_names; sqlite3 uses cursor.description
    if hasattr(cursor, 'column_names'):
        col_names = cursor.column_names
    else:
        col_names = [d[0] for d in cursor.description] if cursor.description else []
    return dict(zip(col_names, row, strict=True))


# ---------------------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------------------


@dataclass
class WritingProfile:
    """Structured writing style profile for a single-user installation."""

    id: str
    tone: str = "semi-formal"  # "formal" | "semi-formal" | "casual" | "friendly"
    sentence_length: str = "medium"  # "short" | "medium" | "long"
    first_person: str = "I"  # "I" | "we" | "they" | "mixed"
    signature_phrases: list[str] = field(default_factory=list)
    greeting_style: str = "Hi [Name],"
    signoff_style: str = "Cheers"
    updated_at: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def from_row(cls, row: dict) -> WritingProfile:
        """Deserialize from a dict (from async sqlite query)."""
        data = dict(row)
        # signature_phrases stored as JSON string
        if isinstance(data.get("signature_phrases"), str):
            data["signature_phrases"] = json.loads(data["signature_phrases"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tone": self.tone,
            "sentence_length": self.sentence_length,
            "first_person": self.first_person,
            "signature_phrases": self.signature_phrases,
            "greeting_style": self.greeting_style,
            "signoff_style": self.signoff_style,
            "updated_at": self.updated_at.isoformat(),
        }


# ---------------------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------------------

STYLE_EXTRACTION_PROMPT = """You are a writing style analyzer. Given the following text, extract the writing style characteristics.

Return a JSON object with exactly these fields:
- "tone": one of "formal", "semi-formal", "casual", "friendly"
- "sentence_length": one of "short" (under 15 words), "medium" (15-25 words), "long" (over 25 words)
- "first_person": one of "I", "we", "they", "mixed"
- "signature_phrases": list of characteristic phrases (e.g. ["cheers", "all the best"])
- "greeting_style": the greeting pattern (e.g. "Hi [Name],", "Hey team,")
- "signoff_style": the sign-off pattern (e.g. "Cheers", "Best", "Thanks")

Text to analyze:
{content}

Return only the JSON object, no markdown or explanation."""


async def extract_style_fields(content: str, llm_complete=None) -> dict[str, Any]:
    """Extract WritingProfile fields from content using an LLM.

    Uses ``llm_router.complete`` internally so that prompts are cached
    when CACHE_PROMPTS=1 (issue #110).

    Args:
        content: The approved draft text (either user-edited or original draft output).
        llm_complete: Async LLM callable. If None, uses router's llm_complete.

    Returns:
        Dict with all WritingProfile fields: tone, sentence_length, first_person,
        signature_phrases, greeting_style, signoff_style.
    """
    if not content or not content.strip():
        return {}

    if llm_complete is None:
        from backend.llm.router import llm_complete as _llm
        llm_complete = _llm

    prompt = STYLE_EXTRACTION_PROMPT.format(content=content[:3000])  # cap at 3000 chars

    try:
        response = await llm_complete(prompt, system="", agent_role=None)
    except Exception:
        return {}

    # Try to extract JSON from response (may be wrapped in markdown code blocks)
    text = response.strip()
    # Strip markdown code block wrappers if present
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        text = text.lstrip("json").lstrip("\n").rstrip("```")  # noqa: B005

    try:
        parsed = json.loads(text)
    except Exception:
        return {}

    # Validate and normalize the returned fields
    valid_tones = {"formal", "semi-formal", "casual", "friendly"}
    valid_lengths = {"short", "medium", "long"}
    valid_first_person = {"I", "we", "they", "mixed"}

    result = {}
    if "tone" in parsed and parsed["tone"] in valid_tones:
        result["tone"] = parsed["tone"]
    if "sentence_length" in parsed and parsed["sentence_length"] in valid_lengths:
        result["sentence_length"] = parsed["sentence_length"]
    if "first_person" in parsed and parsed["first_person"] in valid_first_person:
        result["first_person"] = parsed["first_person"]
    if "signature_phrases" in parsed and isinstance(parsed["signature_phrases"], list):
        result["signature_phrases"] = parsed["signature_phrases"]
    if "greeting_style" in parsed and isinstance(parsed["greeting_style"], str):
        result["greeting_style"] = parsed["greeting_style"]
    if "signoff_style" in parsed and isinstance(parsed["signoff_style"], str):
        result["signoff_style"] = parsed["signoff_style"]

    return result


def _get_draft_content(skill_ctx) -> str:
    """Extract the draft text from skill execution context scratch."""
    draft_node = skill_ctx.scratch.get("draft", {})
    output = draft_node.get("output", {})
    if isinstance(output, dict):
        return output.get("text", "")
    return str(output) if output else ""


# Spec defaults applied by WritingProfileStore.reset() (#53). Single
# source of truth so the deletion route and SharedMemoryStore.delete_all
# can both reference it.
WRITING_PROFILE_DEFAULTS: dict[str, Any] = {
    "tone": "semi-formal",
    "sentence_length": "medium",
    "first_person": "I",
    "signature_phrases": [],
    "greeting_style": "Hi [Name],",
    "signoff_style": "Cheers",
}


class WritingProfileStore:
    """CRUD operations for the WritingProfile singleton (async).

    PGLite (SQLite-compatible) schema must contain a writing_profile table:
      CREATE TABLE IF NOT EXISTS writing_profile (
          id          TEXT PRIMARY KEY,
          tone        TEXT NOT NULL DEFAULT 'semi-formal',
          sentence_length TEXT NOT NULL DEFAULT 'medium',
          first_person TEXT NOT NULL DEFAULT 'I',
          signature_phrases TEXT NOT NULL DEFAULT '[]',
          greeting_style TEXT NOT NULL DEFAULT 'Hi [Name],',
          signoff_style  TEXT NOT NULL DEFAULT 'Cheers',
          updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
      );

    All public methods are async and use a connection pool for non-blocking I/O.
    """

    _SINGLETON_ID = "default"

    def __init__(self, db_path: str | None = None, pool_size: int = 5):
        self.db_path = db_path or ":memory:"
        self._pool = AsyncSQLitePool(self.db_path, pool_size=pool_size)
        self._started = False

    async def start(self) -> None:
        """Initialize the connection pool and schema."""
        if self._started:
            return
        self._started = True
        await self._pool.start()
        await self._ensure_schema()

    async def stop(self) -> None:
        """Stop the connection pool."""
        await self._pool.stop()
        self._started = False

    async def _ensure_schema(self) -> None:
        """Create table and ensure singleton row exists."""
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS writing_profile (
                    id                  TEXT PRIMARY KEY,
                    tone                TEXT NOT NULL DEFAULT 'semi-formal',
                    sentence_length     TEXT NOT NULL DEFAULT 'medium',
                    first_person        TEXT NOT NULL DEFAULT 'I',
                    signature_phrases   TEXT NOT NULL DEFAULT '[]',
                    greeting_style      TEXT NOT NULL DEFAULT 'Hi [Name],',
                    signoff_style       TEXT NOT NULL DEFAULT 'Cheers',
                    updated_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Ensure singleton row exists
            row = await conn.execute(
                "SELECT 1 FROM writing_profile WHERE id = ?", (self._SINGLETON_ID,)
            )
            result = await row.fetchone()
            if not result:
                await conn.execute(
                    "INSERT INTO writing_profile (id) VALUES (?)",
                    (self._SINGLETON_ID,),
                )
            await conn.commit()

    async def get(self) -> WritingProfile:
        """Load the singleton writing profile."""
        row = await self._pool.execute_one(
            "SELECT * FROM writing_profile WHERE id = ?", (self._SINGLETON_ID,)
        )
        if not row:
            # Recreate if missing
            await self._ensure_schema()
            row = await self._pool.execute_one(
                "SELECT * FROM writing_profile WHERE id = ?", (self._SINGLETON_ID,)
            )
        if not row:
            # Still missing — create from spec defaults
            row = {
                "id": self._SINGLETON_ID,
                "tone": "semi-formal",
                "sentence_length": "medium",
                "first_person": "I",
                "signature_phrases": "[]",
                "greeting_style": "Hi [Name],",
                "signoff_style": "Cheers",
            }
        return WritingProfile.from_row(row)

    async def update_style(self, updates: dict[str, Any]) -> WritingProfile:
        """Update style fields from a dict (partial update supported)."""
        valid_fields = {
            "tone",
            "sentence_length",
            "first_person",
            "signature_phrases",
            "greeting_style",
            "signoff_style",
        }
        filtered = {k: v for k, v in updates.items() if k in valid_fields}

        if "signature_phrases" in filtered and isinstance(filtered["signature_phrases"], list):
            filtered["signature_phrases"] = json.dumps(filtered["signature_phrases"])

        filtered["updated_at"] = datetime.utcnow().isoformat()

        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [self._SINGLETON_ID]

        await self._pool.execute_write(
            f"UPDATE writing_profile SET {set_clause} WHERE id = ?",
            tuple(values),
        )

        return await self.get()

    async def reset(self) -> WritingProfile:
        """Reset the singleton writing profile to spec defaults (#53).

        Idempotent -- callable on a missing-row state since update_style()
        flows through _ensure_schema() on the next call.
        """
        return await self.update_style(WRITING_PROFILE_DEFAULTS)

    async def format(self) -> str:
        """Render the profile as a style guide string for prompt injection.

        This is the text injected into agent system prompts so they write in the user's voice.
        """
        p = await self.get()
        greeting_note = '(never "Hey" or "Dear")' if "Hi" in p.greeting_style else ""
        signoff_note = '(never "Best" or "Thanks")' if p.signoff_style != "Best" else ""

        return f"""You are drafting as this user. Their style:
- Tone: {p.tone}
- Avg sentence length: {p.sentence_length}
- First person: "{p.first_person}"
- Signature phrases: {json.dumps(p.signature_phrases)}
- Greeting: "{p.greeting_style}" {greeting_note}
- Sign-off: "{p.signoff_style}" {signoff_note}"""
