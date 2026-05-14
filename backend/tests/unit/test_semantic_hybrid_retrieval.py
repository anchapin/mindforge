"""
Tests for SemanticMemory hybrid BM25 + vector retrieval with RRF fusion.

GREEN phase tests — verifying hybrid search behavior after implementation.
These tests define the expected contract for issue #5.

SPEC reference: §5.7.4 Hybrid Retrieval (BM25 + Vector)
"""

from unittest.mock import AsyncMock, patch

import pytest

from backend.memory import embeddings as embeddings_module
from backend.memory.semantic import SemanticMemory


def _make_fake_emb(texts: list[str], dim: int = 768) -> list[list[float]]:
    """Deterministic fake embeddings keyed on text content.

    Two texts with identical content get identical embeddings (distance=0, similarity=1.0).
    This ensures vector search returns exact matches first.
    """
    import hashlib

    results: list[list[float]] = []
    for text in texts:
        # Hash the text content to get a deterministic seed
        seed = int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)
        vec: list[float] = [float((seed >> (i % 64)) & 1) for i in range(dim)]
        # Normalize to unit length
        norm = sum(v * v for v in vec) ** 0.5
        vec = [v / max(norm, 1e-9) for v in vec]
        results.append(vec)
    return results


async def _fake_embed_texts(texts: list[str], dim: int = 768) -> list[list[float]]:
    """Sync wrapper for fake embedding generation (AsyncMock needs awaitable)."""
    return _make_fake_emb(texts, dim)


@pytest.fixture
def chroma_tmp_dir(tmp_path) -> str:
    """Isolated ChromaDB directory per test."""
    return str(tmp_path / "chroma_test")


# -------------------------------------------------------------------------------------------------
# Helper to patch embed_texts in the embeddings module (not the semantic module's import)
# The semantic module does: from .embeddings import embed_texts
# So patch.object on embeddings_module.embed_texts works because it's the same object
# -------------------------------------------------------------------------------------------------


class TestSemanticMemoryHybridRetrieval:
    """Test SemanticMemory hybrid BM25 + vector retrieval."""

    @pytest.fixture
    def sm(self, chroma_tmp_dir: str) -> SemanticMemory:
        """Create SemanticMemory instance with isolated ChromaDB."""
        return SemanticMemory(chroma_dir=chroma_tmp_dir)

    @pytest.mark.asyncio
    async def test_add_builds_bm25_index(self, sm: SemanticMemory) -> None:
        """add() must call build_bm25_index() so BM25 is ready for retrieval."""
        text = (
            "Python is a programming language that supports multiple paradigms. "
            "It has a comprehensive standard library. "
            "This tutorial covers the basics of Python."
        )
        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            ids = await sm.add(text=text, project_id="test-project")
        assert len(ids) > 0, "add() returned no IDs — chunking or embedding failed"
        assert sm._bm25_index is not None, (
            "build_bm25_index() was not called after add() — BM25 index is None but should be built"
        )

    @pytest.mark.asyncio
    async def test_search_uses_bm25_rrf_fusion(self, sm: SemanticMemory) -> None:
        """search() must use hybrid BM25 + vector RRF fusion when BM25 is available."""
        python_text = (
            "Python is a programming language that supports multiple paradigms. "
            "It has a comprehensive standard library. "
            "This tutorial covers the basics of Python for beginners."
        )
        js_text = (
            "JavaScript is a web development framework used for building React applications. "
            "It supports both frontend and backend development with modern ES6+ syntax."
        )
        ml_text = (
            "Machine learning involves neural networks and deep learning architectures. "
            "These techniques enable computers to learn from data without explicit programming."
        )
        all_texts = [python_text, js_text, ml_text]

        # Embed all texts — same text = same embedding (distance 0, similarity 1.0)
        all_embs = _make_fake_emb(all_texts)

        async def embed_side_effect(texts: list[str]) -> list[list[float]]:
            return _make_fake_emb(texts)

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            for t in all_texts:
                ids = await sm.add(text=t, project_id="p1")
                assert len(ids) > 0, f"add() failed for text: {t[:50]}"

        assert sm._bm25_index is not None, "BM25 index should be built after add()"

        # Query shares "Python" keyword with python_text — BM25 boosts it
        # Use same embedding as python_text so vector also matches
        query_emb = _make_fake_emb([python_text])[0]

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            results = await sm.search(query="Python tutorial", project_id="p1", top_k=3)

        assert len(results) > 0, "search() returned no results"
        result_texts = [r.text for r in results]
        assert any("Python" in t for t in result_texts), (
            f"search() did not use BM25 — expected 'Python' text in results, got: {result_texts}"
        )

    @pytest.mark.asyncio
    async def test_search_without_bm25_falls_back_to_vector(self, sm: SemanticMemory) -> None:
        """When BM25 index is not built, search should still work with vector only."""
        long_text = "Rust is a systems programming language that provides memory safety without garbage collection. It offers zero-cost abstractions and is widely used in high-performance applications."
        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            ids = await sm.add(text=long_text, project_id="p1")
            assert len(ids) > 0, "add() returned no IDs"

        # Explicitly clear BM25 to simulate pre-build state
        sm._bm25_index = None

        # Use same embedding as the stored text so vector similarity = 1.0
        query_emb = _make_fake_emb([long_text])[0]

        async def embed_side_effect(texts: list[str]) -> list[list[float]]:
            return _make_fake_emb(texts)

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            results = await sm.search(query="Rust systems", project_id="p1", top_k=3)

        assert len(results) > 0, "search() should fall back to vector when BM25 unavailable"
        result_texts = [r.text for r in results]
        assert any("Rust" in t for t in result_texts), f"Expected Rust in results: {result_texts}"

    @pytest.mark.asyncio
    async def test_retrieve_combines_bm25_and_vector_scores(self, sm: SemanticMemory) -> None:
        """retrieve() must combine BM25 and vector scores using RRF with k=60."""
        # Texts must be long enough to produce chunks (min_chunk_size=32 tokens)
        text_a = (
            "Python is a programming language widely used for tutorials and beginners guides. "
            "It has clean syntax and extensive libraries that make it ideal for rapid software development."
        )
        text_b = (
            "JavaScript is a language commonly used for React web development and modern frontend frameworks. "
            "It supports both client-side and server-side execution with event-driven architecture."
        )
        text_c = (
            "Python data science ecosystem includes NumPy, Pandas, and ML libraries for data science applications. "
            "These tools provide powerful data manipulation and machine learning capabilities for researchers."
        )
        all_texts = [text_a, text_b, text_c]

        async def embed_side_effect(texts: list[str]) -> list[list[float]]:
            return _make_fake_emb(texts)

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            for t in all_texts:
                ids = await sm.add(text=t, project_id="p1")
                assert len(ids) > 0, f"add() failed for: {t[:50]}"

        # Query embedding = same as text_c (shares "Python" and "data science")
        query_emb = _make_fake_emb([text_c])[0]

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            results = await sm.search(query="Python programming", project_id="p1", top_k=3)

        assert len(results) > 0
        result_texts = [r.text for r in results]
        python_count = sum(1 for t in result_texts if "Python" in t)
        assert python_count >= 1, f"BM25 should boost Python documents, got: {result_texts}"

    @pytest.mark.asyncio
    async def test_retrieve_respects_top_k(self, sm: SemanticMemory) -> None:
        """search() top_k parameter must be respected by the fusion."""
        # Text must be long enough to produce chunks (min_chunk_size=32 tokens)
        long_text = (
            "This is document content that provides detailed information about various topics for testing purposes. "
            "The content covers multiple different subject areas and includes substantial material for analysis. "
            "Each section provides comprehensive coverage of relevant concepts and practical applications."
        )
        all_embs = _make_fake_emb([long_text] * 10)

        async def embed_side_effect(texts: list[str]) -> list[list[float]]:
            return _make_fake_emb(texts)

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            for i in range(10):
                ids = await sm.add(text=long_text, project_id="p1")
                assert len(ids) > 0, f"add() failed for document {i}"

        # Same embedding as stored text → perfect vector match
        query_emb = _make_fake_emb([long_text])[0]

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            results = await sm.search(query="Document", project_id="p1", top_k=3)

        assert len(results) == 3, f"top_k=3 should return exactly 3 results, got {len(results)}"

    @pytest.mark.asyncio
    async def test_search_respects_project_id_scope(self, sm: SemanticMemory) -> None:
        """BM25 and vector search must only score documents matching project_id."""
        # Texts must be long enough to produce chunks (min_chunk_size=32 tokens)
        long_text_a = (
            "Python is a comprehensive programming language widely used for educational tutorials and software development. "
            "It supports multiple programming paradigms including object-oriented, functional, and procedural styles."
        )
        long_text_b = (
            "JavaScript is a versatile language primarily used for web development and building React-based frontend applications. "
            "It enables both client-side and server-side scripting with modern ES6+ syntax features."
        )

        async def embed_side_effect(texts: list[str]) -> list[list[float]]:
            return _make_fake_emb(texts)

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            ids_a = await sm.add(text=long_text_a, project_id="project-a")
            ids_b = await sm.add(text=long_text_b, project_id="project-b")
            assert len(ids_a) > 0, "add() for project-a returned no IDs"
            assert len(ids_b) > 0, "add() for project-b returned no IDs"

        # Use same embedding as project-a text so vector matches that one
        query_emb = _make_fake_emb([long_text_a])[0]

        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=embed_side_effect)
        ):
            results = await sm.search(query="tutorial", project_id="project-a", top_k=5)

        result_texts = [r.text for r in results]
        assert all("JavaScript" not in t for t in result_texts), (
            f"project-a search should not return project-b documents: {result_texts}"
        )


class TestSemanticMemoryBM25Index:
    """Unit tests for BM25 index construction and invalidation."""

    @pytest.fixture
    def sm(self, chroma_tmp_dir: str) -> SemanticMemory:
        return SemanticMemory(chroma_dir=chroma_tmp_dir)

    @pytest.mark.asyncio
    async def test_build_bm25_index_tokenizes_corpus(self, sm: SemanticMemory) -> None:
        """build_bm25_index() must tokenize the corpus for BM25 scoring."""
        # Texts must be long enough to produce chunks (min_chunk_size=32 tokens)
        long_texts = [
            "Machine learning involves neural networks and deep learning architectures that enable computers to learn from data patterns. "
            "These techniques are widely applied across classification, regression, and clustering problems in modern AI systems.",
            "Deep learning transformer architecture has revolutionized natural language processing and computer vision applications. "
            "The self-attention mechanism enables efficient parallel processing of sequential and spatial data.",
        ]
        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            for t in long_texts:
                ids = await sm.add(text=t, project_id="x")
                assert len(ids) > 0, f"add() failed for: {t[:50]}"

        assert sm._bm25_index is not None, "BM25 index should be built"
        from rank_bm25 import BM25Okapi

        assert isinstance(sm._bm25_index, BM25Okapi), "Index should be BM25Okapi instance"

    @pytest.mark.asyncio
    async def test_delete_invalidates_bm25_index(self, sm: SemanticMemory) -> None:
        """delete() must invalidate the BM25 index since corpus changed."""
        # Text must be long enough to produce chunks (min_chunk_size=32 tokens)
        long_text = (
            "This is a test document with sufficient content to produce chunks for BM25 indexing purposes. "
            "It contains multiple sentences with enough tokens to exceed the minimum chunk size threshold."
        )
        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            ids = await sm.add(text=long_text, project_id="x")
            assert len(ids) > 0, "add() returned no IDs"

        assert sm._bm25_index is not None

        # delete() is synchronous — no await needed
        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            sm.delete(ids[0])

        assert sm._bm25_index is None, "BM25 index should be invalidated after delete()"

    @pytest.mark.asyncio
    async def test_delete_all_invalidates_bm25(self, sm: SemanticMemory) -> None:
        """delete_all() must invalidate the BM25 index."""
        # Texts must be long enough to produce chunks (min_chunk_size=32 tokens)
        long_texts = [
            "Document one contains content about programming and software development practices. "
            "This includes code architecture patterns, testing methodologies, and deployment strategies.",
            "Document two contains content about data structures and algorithms for testing purposes. "
            "It covers sorting, searching, graph algorithms, and complexity analysis for performance optimization.",
        ]
        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            for t in long_texts:
                ids = await sm.add(text=t, project_id="x")
                assert len(ids) > 0, f"add() failed for: {t[:50]}"

        assert sm._bm25_index is not None

        # delete_all() is synchronous — no await needed
        with patch.object(
            embeddings_module, "embed_texts", new=AsyncMock(side_effect=_fake_embed_texts)
        ):
            sm.delete_all(project_id="x")

        assert sm._bm25_index is None, "BM25 index should be invalidated after delete_all()"
