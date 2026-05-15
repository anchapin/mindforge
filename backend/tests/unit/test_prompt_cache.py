"""Unit tests for backend.llm.cache.PromptCache (#51, SPEC §5.7.5).

Pin the contract:
  - Cache miss returns None; subsequent get() with the same key returns the
    stored value.
  - Key is the SHA-256 of (model, system, prompt) -- changing ANY component
    invalidates the entry. The system-change invalidation case is required
    by AC #4 of #51.
  - TTL: entries expire after the configured ttl_seconds.
  - LRU eviction at capacity.
  - no_cache=True bypasses both read and write.
  - Env flag CACHE_PROMPTS=true gates the cache module-wide; with it unset,
    get_global_cache().enabled is False and put/get are no-ops.
  - Cache-hit log event carries ONLY the hashed key, never the raw prompt.
"""

from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------------------
# Fixtures: clean env per test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_cache_env(monkeypatch):
    monkeypatch.delenv("CACHE_PROMPTS", raising=False)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_exports_required_helpers():
    import backend.llm.cache as c

    expected = {"PromptCache", "get_global_cache", "make_cache_key"}
    missing = expected - set(dir(c))
    assert not missing, f"missing helpers: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------


class TestKey:
    def test_same_inputs_same_key(self):
        from backend.llm.cache import make_cache_key

        a = make_cache_key(model="gpt-4o", system="be helpful", prompt="hi")
        b = make_cache_key(model="gpt-4o", system="be helpful", prompt="hi")
        assert a == b

    def test_system_change_invalidates_key(self):
        """AC #4 from #51 -- a different system prompt MUST yield a
        different cache key so a system-prompt change cannot serve a stale
        completion."""
        from backend.llm.cache import make_cache_key

        a = make_cache_key(model="gpt-4o", system="be helpful", prompt="hi")
        b = make_cache_key(model="gpt-4o", system="be terse", prompt="hi")
        assert a != b

    def test_model_change_invalidates_key(self):
        from backend.llm.cache import make_cache_key

        a = make_cache_key(model="gpt-4o", system="x", prompt="hi")
        b = make_cache_key(model="gemini", system="x", prompt="hi")
        assert a != b

    def test_prompt_change_invalidates_key(self):
        from backend.llm.cache import make_cache_key

        a = make_cache_key(model="gpt-4o", system="x", prompt="hi")
        b = make_cache_key(model="gpt-4o", system="x", prompt="bye")
        assert a != b

    def test_key_is_hex_digest_not_raw_prompt(self):
        """Key MUST be hashed -- raw prompt content cannot leak into logs."""
        from backend.llm.cache import make_cache_key

        key = make_cache_key(
            model="gpt-4o", system="", prompt="secret api token: sk_live_xxx"
        )
        # SHA-256 hex digest is 64 chars
        assert len(key) == 64
        assert "sk_live" not in key
        assert "secret" not in key


# ---------------------------------------------------------------------------
# PromptCache semantics
# ---------------------------------------------------------------------------


class TestPromptCacheSemantics:
    def test_miss_returns_none(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=4, ttl_seconds=60)
        assert cache.get(model="gpt-4o", system="", prompt="hi") is None

    def test_put_then_get_returns_value(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=4, ttl_seconds=60)
        cache.put(model="gpt-4o", system="", prompt="hi", value="hello!")
        assert cache.get(model="gpt-4o", system="", prompt="hi") == "hello!"

    def test_system_change_invalidates(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=4, ttl_seconds=60)
        cache.put(model="gpt-4o", system="be helpful", prompt="hi", value="A")
        # Same prompt, different system -> miss
        assert cache.get(model="gpt-4o", system="be terse", prompt="hi") is None

    def test_no_cache_bypasses_read(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=4, ttl_seconds=60)
        cache.put(model="gpt-4o", system="", prompt="hi", value="A")
        assert (
            cache.get(model="gpt-4o", system="", prompt="hi", no_cache=True)
            is None
        )

    def test_no_cache_bypasses_write(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=4, ttl_seconds=60)
        cache.put(
            model="gpt-4o", system="", prompt="hi", value="A", no_cache=True
        )
        assert cache.get(model="gpt-4o", system="", prompt="hi") is None

    def test_ttl_expiry(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=4, ttl_seconds=0.05)
        cache.put(model="gpt-4o", system="", prompt="hi", value="A")
        assert cache.get(model="gpt-4o", system="", prompt="hi") == "A"
        time.sleep(0.1)
        assert cache.get(model="gpt-4o", system="", prompt="hi") is None

    def test_lru_eviction_drops_oldest(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=2, ttl_seconds=60)
        cache.put(model="m", system="", prompt="a", value="A")
        cache.put(model="m", system="", prompt="b", value="B")
        cache.put(model="m", system="", prompt="c", value="C")
        # 'a' was least-recently-used -> evicted
        assert cache.get(model="m", system="", prompt="a") is None
        assert cache.get(model="m", system="", prompt="b") == "B"
        assert cache.get(model="m", system="", prompt="c") == "C"

    def test_get_promotes_to_most_recently_used(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=2, ttl_seconds=60)
        cache.put(model="m", system="", prompt="a", value="A")
        cache.put(model="m", system="", prompt="b", value="B")
        # Touch 'a' so 'b' becomes the LRU
        assert cache.get(model="m", system="", prompt="a") == "A"
        cache.put(model="m", system="", prompt="c", value="C")
        # 'b' was now the oldest -> evicted
        assert cache.get(model="m", system="", prompt="b") is None
        assert cache.get(model="m", system="", prompt="a") == "A"

    def test_stats_track_hits_and_misses(self):
        from backend.llm.cache import PromptCache

        cache = PromptCache(capacity=4, ttl_seconds=60)
        cache.get(model="m", system="", prompt="x")  # miss
        cache.put(model="m", system="", prompt="x", value="A")
        cache.get(model="m", system="", prompt="x")  # hit
        cache.get(model="m", system="", prompt="x")  # hit
        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1


# ---------------------------------------------------------------------------
# Global gate -- env flag
# ---------------------------------------------------------------------------


class TestGlobalCacheGate:
    def test_disabled_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("CACHE_PROMPTS", raising=False)
        from backend.llm.cache import get_global_cache

        cache = get_global_cache()
        assert cache.enabled is False

    def test_enabled_when_env_true(self, monkeypatch):
        monkeypatch.setenv("CACHE_PROMPTS", "true")
        from backend.llm.cache import get_global_cache, reset_global_cache

        reset_global_cache()
        cache = get_global_cache()
        assert cache.enabled is True

    def test_disabled_cache_skips_read_and_write(self, monkeypatch):
        """When the global cache is disabled, put/get are silent no-ops --
        Phase 1-4 byte-identical when CACHE_PROMPTS is unset."""
        monkeypatch.delenv("CACHE_PROMPTS", raising=False)
        from backend.llm.cache import get_global_cache, reset_global_cache

        reset_global_cache()
        cache = get_global_cache()
        cache.put(model="m", system="", prompt="hi", value="A")
        assert cache.get(model="m", system="", prompt="hi") is None


# ---------------------------------------------------------------------------
# Hit log event -- never logs raw prompt
# ---------------------------------------------------------------------------


class TestHitLogging:
    def test_hit_emits_event_with_hashed_key_only(self, monkeypatch, caplog):
        """AC #2 from #51 -- the hit log event must include the hashed key
        but NOT the raw prompt or system text."""
        monkeypatch.setenv("CACHE_PROMPTS", "true")
        from backend.llm.cache import get_global_cache, reset_global_cache

        reset_global_cache()
        cache = get_global_cache()
        secret_prompt = "DROP TABLE users; -- secret_marker_for_test"
        cache.put(model="m", system="x", prompt=secret_prompt, value="ok")

        with caplog.at_level("INFO"):
            assert cache.get(model="m", system="x", prompt=secret_prompt) == "ok"

        # Find the cache-hit event
        hit_msgs = [r.message for r in caplog.records if "prompt_cache_hit" in r.message]
        assert hit_msgs, f"no prompt_cache_hit log event found in {[r.message for r in caplog.records]}"
        joined = " ".join(hit_msgs)
        assert "secret_marker_for_test" not in joined
        assert "DROP TABLE" not in joined
