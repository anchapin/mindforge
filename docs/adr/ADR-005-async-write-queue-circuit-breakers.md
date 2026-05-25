# ADR-005: Async Write Queue with Circuit Breakers

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Alex

## Context

Agent outputs (memories, task state, tool results) need to be persisted. Synchronous writes block agent execution and create cascading latency when the DB is slow.

## Decision

Asynchronous write queue with circuit breaker pattern per integration.

## Reasons

- **Non-blocking agent execution**: Agent can proceed while write is queued
- **Circuit breakers per integration**: If ChromaDB is slow, only semantic memory writes are affected; episodic writes (SQLite) continue normally
- **Backpressure handling**: Queue depth bounded; oldest entries evicted under load
- **Failure isolation**: One integration's failure doesn't cascade to others

## Implementation

- In-memory queue per store (episodic, semantic, style)
- Each queue has a circuit breaker with half-open state for recovery
- Thread-safe (using asyncio.Queue)

## Consequences

- Writes are "fire and forget" from agent perspective — no synchronous confirmation
- On crash before flush, writes in queue are lost (acceptable trade-off for single-user)
- Queue depth must be monitored for unbounded growth