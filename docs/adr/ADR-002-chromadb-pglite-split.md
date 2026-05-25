# ADR-002: ChromaDB + PGLite Memory Store Split

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Alex

## Context

MindForge's memory system must support:
- Semantic search over agent-generated content
- Episodic task history with full fidelity
- Style profiles for writing consistency

We evaluated:
1. **ChromaDB + PGLite split** (chosen)
2. pgvector (PostgreSQL extension) — unified store but requires Postgres
3. Qdrant or Weaviate — dedicated vector DB, adds infrastructure

## Decision

ChromaDB (semantic/vector memory) + PGLite/SQLite (episodic + style).

## Reasons

- **ChromaDB is the simplest self-hosted vector store** with a Python-first API. No separate service required in Phase 1 (embedded mode).
- **PGLite as embedded SQL** avoids a PostgreSQL dependency. SQLite is sufficient for single-user workloads and requires zero configuration.
- **Separation of concerns**: Vector DB handles similarity search; SQL handles transactional task state. Each can be tuned independently.
- **Graceful degradation**: If ChromaDB is unavailable, semantic recall degrades but episodic memory (SQLite) continues working.

pgvector would be preferable at scale, but requires a running PostgreSQL instance. The split allows upgrading to pgvector later without architecture change.

## Consequences

- DATA_DIR must contain both `mindforge.db` (SQLite) and ChromaDB persistent volume
- ChromaDB embedded mode is not multi-process safe; concurrent access requires client/server mode
- Two health checks required in /ready endpoint (check_pglite + check_chroma)