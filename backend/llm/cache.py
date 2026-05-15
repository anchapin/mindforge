"""Prompt completion cache (#51, SPEC §5.7.5).

In-memory LRU + TTL cache keyed by SHA-256 of (model, system, prompt).
Single-process by design -- matches the same convention as
asyncio.Semaphore in SPEC §5.5.2 (per-worker, swap to Redis when scaling
to multi-worker).

Phase isolation
---------------
The global cache returned by ``get_global_cache()`` is **disabled** when
the env var ``CACHE_PROMPTS`` is unset / not truthy. In disabled mode
``put`` and ``get`` are silent no-ops -- Phase 1-4 callers see byte-
identical behaviour to the pre-#51 codebase.

Privacy
-------
The cache key is the SHA-256 hex digest of the input tuple. The raw
prompt / system text is **never** logged. The cache-hit log event
carries only the hashed key + the model.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


DEFAULT_CAPACITY = 256
DEFAULT_TTL_SECONDS = 600.0  # 10 minutes


def _flag_enabled() -> bool:
    raw = os.getenv("CACHE_PROMPTS", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def make_cache_key(*, model: str, system: str, prompt: str) -> str:
    """Derive the SHA-256 cache key for the (model, system, prompt) tuple.

    A change to ANY of the three components yields a different digest --
    that's how AC #4 (system-change invalidation) is enforced.
    """
    h = hashlib.sha256()
    # Length-prefix every component so concatenation collisions are
    # impossible (e.g. ("ab", "c") vs ("a", "bc")).
    for part in (model, system, prompt):
        encoded = part.encode("utf-8")
        h.update(len(encoded).to_bytes(8, "big"))
        h.update(encoded)
    return h.hexdigest()


@dataclass
class _Entry:
    value: str
    expires_at: float


class PromptCache:
    """LRU + TTL cache for LLM completions.

    Thread-safe (the FastAPI app may run sync routes on a threadpool).
    """

    def __init__(
        self,
        *,
        capacity: int = DEFAULT_CAPACITY,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        enabled: bool | None = None,
    ) -> None:
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        # Direct construction defaults to enabled=True (a constructed
        # cache is presumably wanted). The global singleton honours the
        # env flag via get_global_cache() instead.
        self.enabled = True if enabled is None else enabled
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    # -----------------------------------------------------------------
    # Public surface
    # -----------------------------------------------------------------

    def get(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        no_cache: bool = False,
    ) -> str | None:
        if not self.enabled or no_cache:
            return None
        key = make_cache_key(model=model, system=system, prompt=prompt)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            if entry.expires_at < time.monotonic():
                # TTL expired -- evict and report miss.
                self._entries.pop(key, None)
                self._misses += 1
                return None
            # LRU promotion: move to end (most-recently-used).
            self._entries.move_to_end(key)
            self._hits += 1
        # Log OUTSIDE the lock; the event carries only the hashed key.
        logger.info("prompt_cache_hit key=%s model=%s", key, model)
        return entry.value

    def put(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        value: str,
        no_cache: bool = False,
    ) -> None:
        if not self.enabled or no_cache:
            return
        key = make_cache_key(model=model, system=system, prompt=prompt)
        expires_at = time.monotonic() + self.ttl_seconds
        with self._lock:
            self._entries[key] = _Entry(value=value, expires_at=expires_at)
            self._entries.move_to_end(key)
            # LRU eviction
            while len(self._entries) > self.capacity:
                self._entries.popitem(last=False)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._entries),
                "capacity": self.capacity,
            }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0


# ---------------------------------------------------------------------------
# Module-level singleton -- the LLMRouter consumes this. Tests can call
# reset_global_cache() to rebuild it after monkeypatching CACHE_PROMPTS.
# ---------------------------------------------------------------------------


_GLOBAL: PromptCache | None = None
_GLOBAL_LOCK = threading.Lock()


def get_global_cache() -> PromptCache:
    global _GLOBAL
    with _GLOBAL_LOCK:
        if _GLOBAL is None:
            _GLOBAL = PromptCache(enabled=_flag_enabled())
        return _GLOBAL


def reset_global_cache() -> None:
    """Rebuild the singleton -- used by tests after toggling env vars."""
    global _GLOBAL
    with _GLOBAL_LOCK:
        _GLOBAL = None
