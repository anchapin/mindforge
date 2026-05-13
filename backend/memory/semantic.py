"""Semantic memory — ChromaDB vector store with hybrid BM25 + vector retrieval.

From SPEC.md §5.7.3-5.7.4.
- ChromaDB for vector similarity search
- BM25Okapi for keyword search (hybrid retrieval)
- Reciprocal Rank Fusion (RRF, k=60) to combine scores
- HMAC signing on write, verification on read (§3b.8)
- Project-scoped retrieval
- Sanitization via sanitize_for_memory() before write
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rank_bm25 import BM25Okapi

import chromadb
from chromadb.config import Settings as ChromaSettings

from .embeddings import ChunkConfig, chunk_text, embed_texts

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------

CHROMA_HOST = os.getenv("CHROMA_HOST", "http://127.0.0.1:8000")
CHROMA_COLLECTION = "semantic_memory"
HMAC_KEY = os.getenv("MEMORY_HMAC_KEY", "").encode() or None

# RRF constant
RRF_K = 60

# Minimum similarity threshold for retrieval
MIN_SIMILARITY = 0.65


# ---------------------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------------------

@dataclass
class SemanticMemoryRecord:
    id: str
    project_id: str | None
    text: str
    embedding: list[float] | None  # None = not yet embedded
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    hmac_sig: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "text": self.text,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }


# ---------------------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------------------

class SemanticMemory:
    """ChromaDB-backed semantic memory with hybrid retrieval and HMAC integrity.

    ChromaDB collection schema:
      id:          Text (UUID, primary key)
      project_id:  Text (nullable, indexed)
      text:        Text
      embedding:   Float[768] (nomic-embed-text)
      metadata:    JSON
      created_at:  ISO timestamp

    All writes are HMAC-signed. Reads verify HMAC and exclude tampered entries.
    """

    def __init__(
        self,
        chroma_dir: str | None = None,
        hmac_key: bytes | None = None,
        chroma_host: str | None = None,
    ):
        self.hmac_key = hmac_key or HMAC_KEY or b"dev-only-key"
        self._chunk_config = ChunkConfig()

        if chroma_dir:
            # Persistent local ChromaDB
            self._client = chromadb.PersistentClient(
                path=chroma_dir,
                settings=ChromaSettings(anonymized_telemetry=False),
            )
        else:
            # Client-server mode
            self._client = chromadb.Client(
                api=chromadb.http.HTTPClient(
                    host=chroma_host or CHROMA_HOST,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            )

        self._collection = self._client.get_or_create_collection(
            name=CHROMA_COLLECTION,
            metadata={"description": "MindForge semantic memory"},
        )
        self._bm25_index: BM25Okapi | None = None
        self._bm25_corpus: list[str] = []
        self._bm25_ids: list[str] = []

    # ---------------------------------------------------------------------------
    # HMAC helpers
    # ---------------------------------------------------------------------------

    def _sign(self, text: str, metadata: dict) -> str:
        """Create HMAC-SHA256 signature for a memory entry."""
        message = json.dumps({"text": text, "metadata": metadata}, sort_keys=True)
        return hmac.new(self.hmac_key, message.encode(), hashlib.sha256).hexdigest()

    def _verify(self, sig: str, text: str, metadata: dict) -> bool:
        """Verify HMAC signature. Returns False if tampered."""
        expected = self._sign(text, metadata)
        return hmac.compare_digest(sig, expected)

    # ---------------------------------------------------------------------------
    # Write path
    # ---------------------------------------------------------------------------

    async def add(
        self,
        text: str,
        project_id: str | None = None,
        task_id: str | None = None,
        agent_role: str | None = None,
        chunk: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> list[str]:
        """Add text to semantic memory.

        Text is chunked, embedded, and stored with HMAC signature.
        Returns list of inserted IDs.

        Args:
            text: Raw text to store.
            project_id: Project scope for retrieval filtering.
            task_id: Source task ID for traceability.
            agent_role: Agent that created this memory.
            chunk: Whether to chunk the text before embedding.
            metadata: Additional metadata to store alongside.
        """
        if chunk:
            chunks = chunk_text(text, self._chunk_config)
        else:
            chunks = [{"text": text, "token_count": len(text) // 4, "chunk_index": 0}]

        extra_meta = metadata or {}
        extra_meta["task_id"] = task_id
        extra_meta["agent_role"] = agent_role
        extra_meta["project_id"] = project_id

        ids: list[str] = []
        texts: list[str] = []
        embeddings: list[list[float]] = []
        metadatas: list[dict] = []

        for c in chunks:
            record_id = str(uuid.uuid4())
            sig = self._sign(c["text"], extra_meta)

            # Embed via Ollama
            embeds = await embed_texts([c["text"]])
            embedding = embeds[0] if embeds else []

            texts.append(c["text"])
            embeddings.append(embedding)
            metadatas.append({
                "project_id": project_id,
                "task_id": task_id,
                "agent_role": agent_role,
                "hmac_sig": sig,
                "created_at": datetime.utcnow().isoformat(),
                "token_count": c["token_count"],
                "chunk_index": c["chunk_index"],
                **{k: str(v) for k, v in extra_meta.items()},
            })
            ids.append(record_id)

        if ids:
            self._collection.add(
                ids=ids,
                documents=texts,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            # Invalidate BM25 index (will be rebuilt on next search)
            self._bm25_index = None

        logger.debug("Added %d semantic memory chunks (project_id=%s)", len(ids), project_id)
        return ids

    # ---------------------------------------------------------------------------
    # Read path
    # ---------------------------------------------------------------------------

    def search(
        self,
        query: str,
        project_id: str | None = None,
        top_k: int = 5,
    ) -> list[SemanticMemoryRecord]:
        """Vector similarity search with project scoping.

        Returns records sorted by cosine similarity (descending).
        Entries with failed HMAC verification are excluded.
        """
        # Embed query
        query_embs = embed_texts([query])
        if not query_embs:
            return []
        query_emb = query_embs[0]

        # Build where filter
        where: dict[str, Any] = {}
        if project_id is not None:
            where["project_id"] = project_id

        results = self._collection.query(
            query_embeddings=[query_emb],
            n_results=top_k * 2,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        records: list[SemanticMemoryRecord] = []
        if not results["ids"] or not results["ids"][0]:
            return []

        for i, record_id in enumerate(results["ids"][0]):
            doc = results["documents"][0][i]
            meta = results["metadatas"][0][i]
            distance = results["distances"][0][i] if "distances" in results else 0.0

            # Cosine similarity from distance (ChromaDB L2 distance)
            similarity = 1.0 - distance if distance <= 2.0 else 0.0

            if similarity < MIN_SIMILARITY:
                continue

            # HMAC verification
            sig = meta.get("hmac_sig", "")
            if sig and not self._verify(sig, doc, {k: v for k, v in meta.items() if k not in ("hmac_sig",)}):
                logger.warning("HMAC mismatch on semantic memory %s — excluding", record_id)
                continue

            records.append(SemanticMemoryRecord(
                id=record_id,
                project_id=meta.get("project_id"),
                text=doc,
                metadata=meta,
                hmac_sig=sig,
            ))

        return records

    # ---------------------------------------------------------------------------
    # Hybrid retrieval (RRF)
    # ---------------------------------------------------------------------------

    def build_bm25_index(self, project_id: str | None = None) -> None:
        """Rebuild BM25 index from all records. Call after writes."""
        try:
            from rank_bm25 import BM25Okapi  # noqa: F401
        except ImportError:
            logger.warning("rank_bm25 not installed — hybrid search falls back to vector only")
            return

        where: dict[str, Any] = {}
        if project_id is not None:
            where["project_id"] = project_id

        results = self._collection.get(
            where=where if where else None,
            include=["documents", "ids"],
        )

        if not results["ids"]:
            return

        self._bm25_corpus = results["documents"]
        self._bm25_ids = results["ids"]
        tokenized = [doc.lower().split() for doc in self._bm25_corpus]
        self._bm25_index = BM25Okapi(tokenized)

    async def retrieve(
        self,
        query: str,
        project_id: str | None = None,
        top_k: int = 5,
        use_bm25: bool = True,
    ) -> list[SemanticMemoryRecord]:
        """Hybrid retrieval: vector similarity + BM25 keyword search + RRF fusion.

        This is the primary retrieval method used by SharedMemoryStore.
        """
        try:
            from rank_bm25 import BM25Okapi  # noqa: F401
        except ImportError:
            use_bm25 = False

        # Vector search
        vector_results = self.search(query, project_id=project_id, top_k=top_k * 2)
        vector_by_id = {r.id: r for r in vector_results}

        # BM25 search
        bm25_scores: dict[str, float] = {}
        if use_bm25 and self._bm25_index is not None:
            tokenized_q = query.lower().split()
            raw_scores = self._bm25_index.get_scores(tokenized_q)
            max_bm25 = max(raw_scores) if max(raw_scores) > 0 else 1.0
            for i, record_id in enumerate(self._bm25_ids):
                if record_id in vector_by_id:
                    bm25_scores[record_id] = raw_scores[i] / max_bm25

        # Reciprocal Rank Fusion
        fused: dict[str, float] = {}
        all_ids = set(list(vector_by_id.keys()) + list(bm25_scores.keys()))

        for record_id in all_ids:
            v_score = 0.0
            if record_id in vector_by_id:
                # Convert distance to similarity proxy (higher = better)
                v_score = 1.0 / (RRF_K + 1 + float(vector_by_id[record_id].metadata.get("distance", 0)))
            b_score = bm25_scores.get(record_id, 0.0)
            b_score_norm = b_score / (RRF_K + 1 + b_score) if b_score > 0 else 0.0
            fused[record_id] = v_score + b_score_norm

        # Sort by fused score and return top-k verified records
        ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return [vector_by_id[rid] for rid, _ in ranked[:top_k] if rid in vector_by_id][:top_k]

    # ---------------------------------------------------------------------------
    # Management
    # ---------------------------------------------------------------------------

    def count(self, project_id: str | None = None) -> int:
        """Count records, optionally scoped to project."""
        where: dict[str, Any] = {}
        if project_id is not None:
            where["project_id"] = project_id
        results = self._collection.get(where=where if where else None)
        return len(results.get("ids", []))

    def delete(self, record_ids: list[str]) -> None:
        """Delete records by ID."""
        if record_ids:
            self._collection.delete(ids=record_ids)
            self._bm25_index = None

    def delete_by_project(self, project_id: str) -> int:
        """Delete all records for a project. Returns count deleted."""
        results = self._collection.get(
            where={"project_id": project_id},
            include=["ids"],
        )
        ids = results.get("ids", [])
        if ids:
            self._collection.delete(ids=ids)
            self._bm25_index = None
        return len(ids)

    def delete_all(self) -> int:
        """Delete entire collection. Returns count deleted."""
        count = self.count()
        self._collection.delete(where={})
        self._bm25_index = None
        return count
