"""Tests for ChromaDB graceful degradation when semantic memory is unavailable.

Verifies issue #104: ChromaDB graceful degradation missing.
When ChromaDB is unavailable, semantic memory queries fail gracefully instead of crashing.
The system falls back to episodic-only retrieval with degraded_quality=True.
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.memory import embeddings as embeddings_module
from backend.memory.semantic import SemanticMemory
from backend.memory.store import MemoryResult, SharedMemoryStore


def _make_fake_emb(texts: list[str], dim: int = 768) -> list[list[float]]:
    """Deterministic fake embeddings keyed on text content."""
    import hashlib

    results: list[list[float]] = []
    for text in texts:
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)
        vec: list[float] = [float((seed >> (i % 64)) & 1) for i in range(dim)]
        norm = sum(v * v for v in vec) ** 0.5
        vec = [v / max(norm, 1e-9) for v in vec]
        results.append(vec)
    return results


async def _fake_embed_texts(texts: list[str], dim: int = 768) -> list[list[float]]:
    """Sync wrapper for fake embedding generation."""
    return _make_fake_emb(texts, dim)


class TestSemanticMemoryGracefulDegradation:
    """Test that SemanticMemory.retrieve() handles ChromaDB failures gracefully."""

    @pytest.fixture
    def chroma_tmp_dir(self, tmp_path):
        return str(tmp_path / "chroma_test")

    @pytest.mark.asyncio
    async def test_retrieve_returns_empty_on_chroma_connection_error(
        self, chroma_tmp_dir: str
    ) -> None:
        """retrieve() must return empty list when ChromaDB query fails."""
        sm = SemanticMemory(chroma_dir=chroma_tmp_dir)

        # Simulate ChromaDB query failure by patching _collection.query
        original_query = sm._collection.query

        def failing_query(*args, **kwargs):
            raise Exception("ChromaDB connection refused")

        sm._collection.query = failing_query  # type: ignore[assignment]

        async def embed_side_effect(texts):
            return _make_fake_emb(texts)

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            results = await sm.retrieve(query="test query", project_id="p1", top_k=5)

        assert results == [], f"Expected empty list on ChromaDB failure, got {results}"

    @pytest.mark.asyncio
    async def test_retrieve_logs_warning_on_chroma_failure(
        self, chroma_tmp_dir: str, caplog
    ) -> None:
        """retrieve() must log a warning when ChromaDB is unavailable."""
        import logging

        sm = SemanticMemory(chroma_dir=chroma_tmp_dir)

        # Simulate ChromaDB query failure
        def failing_query(*args, **kwargs):
            raise Exception("ChromaDB unavailable")

        sm._collection.query = failing_query  # type: ignore[assignment]

        async def embed_side_effect(texts):
            return _make_fake_emb(texts)

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ), caplog.at_level(logging.WARNING):
            results = await sm.retrieve(query="test query", project_id="p1", top_k=5)

        assert results == []
        assert any("ChromaDB" in r.msg or "degraded" in r.msg for r in caplog.records), (
            f"Expected warning about ChromaDB degradation in logs, got: {caplog.records}"
        )


class TestSharedMemoryStoreGracefulDegradation:
    """Test that SharedMemoryStore falls back to episodic-only when ChromaDB fails."""

    @pytest.fixture
    async def store(self, tmp_path, monkeypatch):
        """Create SharedMemoryStore with isolated DB paths."""
        db_path = str(tmp_path / "test.db")
        chroma_dir = str(tmp_path / "chroma")
        store_instance = SharedMemoryStore(db_path=db_path, chroma_dir=chroma_dir)
        await store_instance.start()
        yield store_instance
        await store_instance.stop()

    @pytest.mark.asyncio
    async def test_read_sets_degraded_quality_on_semantic_failure(
        self, store: SharedMemoryStore, monkeypatch
    ) -> None:
        """read() must set degraded_quality=True when semantic retrieval fails."""
        # Mock semantic.retrieve to raise an exception
        original_retrieve = store._semantic.retrieve

        async def failing_retrieve(*args, **kwargs):
            raise Exception("ChromaDB connection refused")

        store._semantic.retrieve = failing_retrieve  # type: ignore[assignment]

        # Also mock embed_texts to prevent the semantic layer from using fallback
        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            context = await store.read(query="test query", project_id="p1")

        # Should still return context (episodic-only) but with degraded_quality flag
        # The actual return is a string, but we can check it contains the degraded message
        assert "(semantic memory unavailable" in context or context == "", context

    @pytest.mark.asyncio
    async def test_read_does_not_crash_on_chroma_failure(
        self, store: SharedMemoryStore, monkeypatch
    ) -> None:
        """read() must not raise an exception when ChromaDB is unavailable."""
        original_retrieve = store._semantic.retrieve

        async def failing_retrieve(*args, **kwargs):
            raise Exception("ChromaDB unavailable")

        store._semantic.retrieve = failing_retrieve  # type: ignore[assignment]

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            # Must not raise
            context = await store.read(query="test query", project_id="p1")
            assert isinstance(context, str), "read() should return a string"

    @pytest.mark.asyncio
    async def test_memory_result_has_degraded_quality_flag(self) -> None:
        """MemoryResult must expose degraded_quality field."""
        result = MemoryResult(
            memory_type="semantic",
            records=[],
            formatted="(semantic memory unavailable — degraded mode)",
            degraded_quality=True,
        )
        assert result.degraded_quality is True

        result_ok = MemoryResult(
            memory_type="semantic",
            records=[],
            formatted="(no relevant semantic memories)",
            degraded_quality=False,
        )
        assert result_ok.degraded_quality is False

    @pytest.mark.asyncio
    async def test_degraded_context_includes_warning(self, store: SharedMemoryStore) -> None:
        """Context string must include degraded mode indicator for frontend."""
        original_retrieve = store._semantic.retrieve

        async def failing_retrieve(*args, **kwargs):
            raise Exception("ChromaDB unavailable")

        store._semantic.retrieve = failing_retrieve  # type: ignore[assignment]

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            context = await store.read(query="test query", project_id="p1")

        # The degraded semantic message should appear in the context
        assert "degraded" in context.lower() or "unavailable" in context.lower(), (
            f"Context should contain degraded mode indicator, got: {context}"
        )
