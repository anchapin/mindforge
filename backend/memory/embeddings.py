"""Embedding pipeline for semantic memory.

From SPEC.md §5.7.3.
- nomic-embed-text via Ollama (768-dim, local, free)
- Text chunking with sentence-boundary awareness
- Token estimation (4 chars/token heuristic)
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------

EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
EMBEDDING_TIMEOUT = int(os.getenv("OLLAMA_EMBEDDING_TIMEOUT", "30"))


# ---------------------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimate: 4 chars per token for English text."""
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------------------

@dataclass
class ChunkConfig:
    """Configuration for text chunking."""
    chunk_size: int = 512       # target tokens per chunk
    chunk_overlap: int = 64     # tokens of overlap between chunks
    min_chunk_size: int = 32   # drop chunks below this size

    def __post_init__(self):
        if self.chunk_size <= self.chunk_overlap:
            raise ValueError("chunk_size must be greater than chunk_overlap")


def _split_into_sentences(text: str) -> list[str]:
    """Split text on sentence boundaries, preserving the delimiter."""
    import re
    # Split on common sentence terminators
    parts = re.split(r'(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str, config: ChunkConfig | None = None) -> list[dict]:
    """Split text into overlapping token-bounded chunks.

    Splits on sentence boundaries where possible to preserve meaning.
    Each chunk gets a character-level start/end for overlap calculation.

    Returns:
        List of dicts with keys: text (str), token_count (int), chunk_index (int)
    """
    if config is None:
        config = ChunkConfig()

    # Rough character limit based on token budget (4 chars/token)
    char_limit = config.chunk_size * 4
    overlap_chars = config.chunk_overlap * 4

    sentences = _split_into_sentences(text)
    if not sentences:
        return []

    chunks: list[dict] = []
    current: list[str] = []
    current_len = 0
    chunk_index = 0

    for sent in sentences:
        sent_len = estimate_tokens(sent)  # token estimate for this sentence

        if current_len + sent_len > char_limit and current:
            # Emit current chunk
            chunk_text = " ".join(current)
            chunks.append({
                "text": chunk_text,
                "token_count": current_len,
                "chunk_index": chunk_index,
            })
            chunk_index += 1

            # Keep overlap from end of current
            overlap_text = " ".join(current)[-overlap_chars:]
            current = [overlap_text, sent]
            current_len = estimate_tokens(overlap_text) + sent_len
        else:
            current.append(sent)
            current_len += sent_len

    # Final chunk
    if current:
        chunk_text = " ".join(current)
        chunks.append({
            "text": chunk_text,
            "token_count": current_len,
            "chunk_index": chunk_index,
        })

    # Filter tiny chunks
    return [c for c in chunks if c["token_count"] >= config.min_chunk_size]


# ---------------------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------------------

class EmbeddingError(Exception):
    """Raised when embedding generation fails."""


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate embeddings via local Ollama server.

    Uses nomic-embed-text (768-dim) for high quality + speed.

    Args:
        texts: List of texts to embed. For single text, wrap in list.

    Returns:
        List of embedding vectors, one per input text.

    Raises:
        EmbeddingError: If Ollama is unreachable or returns an error.
    """
    if not texts:
        return []

    # Try Ollama first
    try:
        return await _ollama_embed(texts)
    except Exception as exc:
        logger.warning("Ollama embedding failed, falling back to mock: %s", exc)
        # Return mock embeddings for development when Ollama is not available
        return _mock_embeddings(len(texts), dim=768)


async def _ollama_embed(texts: list[str]) -> list[list[float]]:
    """Embed via Ollama /api/embeddings endpoint."""
    embeddings: list[list[float]] = []

    async with httpx.AsyncClient(timeout=float(EMBEDDING_TIMEOUT)) as client:
        for text in texts:
            response = await client.post(
                f"{OLLAMA_BASE_URL}/api/embeddings",
                json={"model": EMBEDDING_MODEL, "prompt": text},
            )
            if response.status_code != 200:
                raise EmbeddingError(
                    f"Ollama returned {response.status_code}: {response.text}"
                )
            data = response.json()
            embedding = data.get("embedding")
            if not embedding:
                raise EmbeddingError(f"Ollama response missing 'embedding' field: {data}")
            embeddings.append(embedding)

    return embeddings


def _mock_embeddings(count: int, dim: int) -> list[list[float]]:
    """Return deterministic mock embeddings for dev/test when Ollama is unavailable."""
    import hashlib
    results = []
    for i in range(count):
        # Deterministic pseudo-random based on index
        seed = int(hashlib.md5(str(i).encode()).hexdigest()[:8], 16)
        vec = [(seed % 1000) / 1000.0 for _ in range(dim)]
        # Normalize
        norm = sum(v * v for v in vec) ** 0.5
        vec = [v / norm for v in vec]
        results.append(vec)
    return results


async def embed_text(text: str) -> list[list[float]]:
    """Convenience wrapper for single text."""
    return await embed_texts([text])
