# ADR-006: SQLite Checkpointer for LangGraph Persistence

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Alex

## Context

LangGraph supports checkpointer persistence to resume agent state after restarts. We chose SQLite over PostgreSQL or Redis for the checkpointer store.

## Decision

SQLite checkpointer at `$DATA_DIR/checkpoints.db`.

## Reasons

- **Zero infrastructure**: SQLite is a file, no server process needed
- **Sufficiency for single-user**: Checkpointer stores graph state snapshots; single-user has minimal concurrent checkpoint writes
- **Persistence portability**: The SQLite file can be backed up with standard file tools
- **DataDir collocation**: Keeps all persistent state in DATA_DIR

## Consequences

- SQLite checkpointer is not multi-process safe under concurrent access. Acceptable for single-user.
- Checkpoints accumulate; periodic cleanup of old checkpoints is TODO
- Checkpoint schema must be backwards-compatible across MindForge upgrades