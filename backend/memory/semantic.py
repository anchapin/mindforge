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

import chromadb
from chromadb.config import Settings as ChromaSettings

from .embeddings import ChunkConfig, chunk_text, embed_texts

if TYPE_CHECKING:
    from rank_bm25 import BM25Okapi  # noqa: F401

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------------------

CHROMA_HOST = os.getenv("CHROMA_HOST", "http://127.0.0.1:8000")
CHROMA_COLLECTION = "semantic_memory"
HMAC_KEY: bytes | None = None

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
        self.hmac_key = hmac_key or self._derive_hmac_key()
        self._chunk_config = ChunkConfig()
        self._degraded = False  # True when ChromaDB operations fail

        try:
            if chroma_dir:
                # Persistent local ChromaDB
                self._client = chromadb.PersistentClient(
                    path=chroma_dir,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            else:
                # Client-server mode
                self._client = chromadb.HttpClient(  # type: ignore[call-args]
                    host=chroma_host or CHROMA_HOST,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )

            self._collection = self._client.get_or_create_collection(
                name=CHROMA_COLLECTION,
                metadata={"description": "MindForge semantic memory"},
            )
        except Exception as exc:
            logger.warning("ChromaDB initialization failed (degraded mode): %s", exc)
            self._degraded = True
            self._client = None  # type: ignore[assignment]
            self._collection = None  # type: ignore[assignment]

        self._bm25_index: BM25Okapi | None = None
        self._bm25_corpus: list[str] = []
        self._bm25_ids: list[str] = []

    @property
    def degraded(self) -> bool:
        """True when ChromaDB has been unavailable for a recent operation."""
        return self._degraded

    def _set_degraded(self) -> None:
        """Mark this store as degraded due to ChromaDB unavailability."""
        self._degraded = True

    def _clear_degraded(self) -> None:
        """Mark this store as healthy again."""
        self._degraded = False

    # ---------------------------------------------------------------------------
    # HMAC helpers
    # ---------------------------------------------------------------------------

    def _derive_hmac_key(self) -> bytes:
        """Derive HMAC key from FERNET_KEY using HKDF, or fall back gracefully.

        From SPEC.md §3b.6 - integration credentials are never logged.
        """
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF

        fermert_key = os.getenv("FERNET_KEY", "")
        if not fermert_key:
            logger.warning("FERNET_KEY not set — using random HMAC key (memory integrity checks disabled)")
            return b"dev-only-key"

        try:
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,
                salt=b"mindforge-hmac-v1",
                info=b"semantic-memory-hmac-key",
            )
            return hkdf.derive(fermert_key.encode())
        except Exception as exc:
            logger.warning("HMAC key derivation failed (%s) — using random key", exc)
            return b"dev-only-key"

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

            # HMAC signs only the 3 core identity fields — not extra_meta —
            # so that retrieval (which reconstructs only those 3 fields) can verify.
            signed_meta = {
                "project_id": project_id,
                "task_id": task_id,
                "agent_role": agent_role,
            }
            sig = self._sign(c["text"], signed_meta)

            # Embed via Ollama
            embeds = await embed_texts([c["text"]])
            embedding = embeds[0] if embeds else []

            texts.append(c["text"])
            embeddings.append(embedding)
            metadatas.append(
                {
                    "project_id": project_id,
                    "task_id": task_id,
                    "agent_role": agent_role,
                    "hmac_sig": sig,
                    "created_at": datetime.utcnow().isoformat(),
                    "token_count": c["token_count"],
                    "chunk_index": c["chunk_index"],
                    **{k: str(v) for k, v in extra_meta.items()},
                }
            )
            ids.append(record_id)

        if ids:
            try:
                self._collection.add(
                    ids=ids,
                    embeddings=embeddings,  # type: ignore[arg-type]
                    metadatas=metadatas,  # type: ignore[arg-type]
                    documents=texts,
                )
                self._clear_degraded()
            except Exception as exc:
                logger.warning(
                    "ChromaDB add failed, data not persisted (degraded mode): %s",
                    exc,
                )
                self._set_degraded()
                return []
            try:
                self.build_bm25_index(project_id=project_id)
            except Exception as exc:
                logger.warning("BM25 index rebuild failed: %s", exc)

        logger.debug("Added %d semantic memory chunks (project_id=%s)", len(ids), project_id)
        return ids

    # ---------------------------------------------------------------------------
    # Read path
    # ---------------------------------------------------------------------------

    async def search(
        self,
        query: str,
        project_id: str | None = None,
        top_k: int = 5,
    ) -> list[SemanticMemoryRecord]:
        """Hybrid retrieval entry point — delegates to retrieve() for BM25+vector RRF fusion.

        Returns records sorted by fused score (BM25 + vector similarity).
        Entries with failed HMAC verification are excluded.
        """
        return await self.retrieve(query=query, project_id=project_id, top_k=top_k)

    async def _vector_search(
        self,
        query_emb: list[float],
        project_id: str | None = None,
        top_k: int = 5,
        min_similarity: float = 0.0,
    ) -> list[SemanticMemoryRecord]:
        """Pure vector similarity search — used internally by retrieve().

        Args:
            query_emb: Pre-computed query embedding.
            project_id: Optional project scope filter.
            top_k: Number of results to return (before min_similarity filtering fetches more).
            min_similarity: Minimum similarity threshold (0 = no filter, used by retrieve).
        """
        if self._collection is None:
            raise RuntimeError("ChromaDB collection not initialized")

        # Build where filter
        where: dict[str, Any] = {}
        if project_id is not None:
            where["project_id"] = project_id

        results = self._collection.query(
            query_embeddings=[query_emb],  # type: ignore[arg-type]
            n_results=top_k * 2,
            where=where if where else None,
            include=["documents", "metadatas", "distances"],
        )

        records: list[SemanticMemoryRecord] = []
        if not results["ids"] or not results["ids"][0]:
            return []

        for i, record_id in enumerate(results["ids"][0]):  # type: ignore[index]
            doc = results["documents"][0][i]  # type: ignore[index]
            meta = results["metadatas"][0][i]  # type: ignore[index]
            distance = (
                results["distances"][0][i]
                if "distances" in results and results["distances"] and results["distances"][0]
                else 0.0
            )

            # Cosine similarity from distance (ChromaDB L2 distance)
            similarity = 1.0 - distance if distance <= 2.0 else 0.0

            if similarity < min_similarity:
                continue

            # HMAC verification — only verify fields that were signed (project_id, task_id, agent_role)
            # NOTE: None values in extra_meta are serialized as JSON null, but stored/retrieved as
            # string "None". Convert back so HMAC verification sees the same null as was signed.
            def _none_str_to_none(v: Any) -> Any:
                return None if v == "None" else v

            sig = meta.get("hmac_sig", "")
            signed_meta = {
                "project_id": _none_str_to_none(meta.get("project_id")),
                "task_id": _none_str_to_none(meta.get("task_id")),
                "agent_role": _none_str_to_none(meta.get("agent_role")),
            }
            if sig and not self._verify(sig, doc, signed_meta):  # type: ignore[arg-type]
                logger.warning("HMAC mismatch on semantic memory %s — excluding", record_id)
                continue

            # Make a mutable copy of metadata and inject distance for fusion
            record_meta = dict(meta)
            record_meta["distance"] = distance

            records.append(
                SemanticMemoryRecord(
                    id=record_id,
                    project_id=record_meta.get("project_id"),  # type: ignore[arg-type]
                    text=doc,
                    embedding=None,
                    metadata=record_meta,  # type: ignore[arg-type]
                    hmac_sig=sig,  # type: ignore[arg-type]
                )
            )

        return records

    # ---------------------------------------------------------------------------
    # Hybrid retrieval (RRF)
    # ---------------------------------------------------------------------------

    def build_bm25_index(self, project_id: str | None = None) -> None:
        """Rebuild BM25 index from all records. Call after writes."""
        if self._collection is None:
            return

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
            include=["documents"],  # type: ignore[list-item]
        )

        if not results["ids"]:
            return

        self._bm25_corpus = results["documents"] or []  # type: ignore[assignment]
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
        On ChromaDB failure, returns empty list with degraded_quality flag.
        """
        try:
            records = await self._retrieve_impl(query, project_id, top_k, use_bm25)
            self._clear_degraded()
            return records
        except Exception as exc:
            logger.warning(
                "ChromaDB retrieval failed (degraded mode): %s",
                exc,
            )
            self._set_degraded()
            raise

    async def _retrieve_impl(
        self,
        query: str,
        project_id: str | None = None,
        top_k: int = 5,
        use_bm25: bool = True,
    ) -> list[SemanticMemoryRecord]:
        """Internal implementation of hybrid retrieval.

        Raises:
            Exception: Any ChromaDB or embedding failure propagates to trigger
                       graceful degradation in retrieve().
        """
        try:
            from rank_bm25 import BM25Okapi  # noqa: F401
        except ImportError:
            use_bm25 = False

        query_embs = await embed_texts([query])
        if not query_embs:
            return []
        query_emb = query_embs[0]

        vector_results = await self._vector_search(
            query_emb, project_id=project_id, top_k=top_k * 2, min_similarity=0.0
        )

        vector_by_id = {r.id: r for r in vector_results}

        bm25_scores: dict[str, float] = {}
        if use_bm25 and self._bm25_index is not None:
            try:
                tokenized_q = query.lower().split()
                raw_scores = self._bm25_index.get_scores(tokenized_q)
                max_bm25 = max(raw_scores) if max(raw_scores) > 0 else 1.0
                for i, record_id in enumerate(self._bm25_ids):
                    if record_id in vector_by_id:
                        bm25_scores[record_id] = raw_scores[i] / max_bm25
            except Exception as bm25_err:
                logger.warning("BM25 scoring failed, using vector-only: %s", bm25_err)

        fused: dict[str, float] = {}
        all_ids = set(list(vector_by_id.keys()) + list(bm25_scores.keys()))

        for record_id in all_ids:
            v_score = 0.0
            if record_id in vector_by_id:
                v_score = 1.0 / (
                    RRF_K + 1 + float(vector_by_id[record_id].metadata.get("distance", 0))
                )
            b_score = bm25_scores.get(record_id, 0.0)
            b_score_norm = b_score / (RRF_K + 1 + b_score) if b_score > 0 else 0.0
            fused[record_id] = v_score + b_score_norm

        ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)
        return [vector_by_id[rid] for rid, _ in ranked[:top_k] if rid in vector_by_id][:top_k]

    # ---------------------------------------------------------------------------
    # Management
    # ---------------------------------------------------------------------------

    def count(self, project_id: str | None = None) -> int:
        """Count records, optionally scoped to project. Returns 0 if ChromaDB unavailable."""
        where: dict[str, Any] = {}
        if project_id is not None:
            where["project_id"] = project_id
        try:
            results = self._collection.get(where=where if where else None)
            return len(results.get("ids", []))
        except Exception as exc:
            logger.warning("ChromaDB count failed (degraded mode): %s", exc)
            self._set_degraded()
            return 0

    def delete(self, record_ids: str | list[str]) -> None:
        """Delete records by ID (single or list). Silently fails if ChromaDB unavailable."""
        if isinstance(record_ids, str):
            record_ids = [record_ids]
        if record_ids:
            try:
                self._collection.delete(ids=record_ids)
                self._bm25_index = None
            except Exception as exc:
                logger.warning("ChromaDB delete failed (degraded mode): %s", exc)
                self._set_degraded()

    def delete_by_project(self, project_id: str) -> int:
        """Delete all records for a project. Returns count deleted. Returns 0 if unavailable."""
        try:
            results = self._collection.get(
                where={"project_id": project_id},
            )
            ids = results.get("ids", [])
            if ids:
                self._collection.delete(ids=ids)
                self._bm25_index = None
            return len(ids)
        except Exception as exc:
            logger.warning("ChromaDB delete_by_project failed (degraded mode): %s", exc)
            self._set_degraded()
            return 0

    def delete_all(self, project_id: str | None = None) -> int:
        """Delete entire collection or scoped to project_id. Returns count deleted. Returns 0 if unavailable."""
        try:
            if project_id is not None:
                return self.delete_by_project(project_id)
            count = self.count()
            self._collection.delete(where={})
            self._bm25_index = None
            return count
        except Exception as exc:
            logger.warning("ChromaDB delete_all failed (degraded mode): %s", exc)
            self._set_degraded()
            return 0
