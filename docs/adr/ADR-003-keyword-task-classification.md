# ADR-003: Keyword-Based Task Type Classification

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Alex

## Context

When a user submits a task, the supervisor must classify it into one of the four agent types:
- `code` → Engineer
- `write` / `campaign` / `content` → CMO
- `research` / `analyze` / `report` → Researcher
- `orchestrate` / `coordinate` / `manage` → COO

LLM-based classification would be more flexible but introduces latency, cost, and non-determinism for a simple routing decision.

## Decision

Keyword-based `classify_task_type()` function in the supervisor module.

## Reasons

- **Speed**: String matching is ~1ms vs 200-500ms for an LLM call
- **Determinism**: Same input always routes same way — easier to test and debug
- **Transparency**: Exact matching criteria are inspectable code, not a model behavior
- **Sufficiency**: For single-user with predictable task vocabulary, keyword matching covers 90%+ of cases correctly

If the classifier fails (unknown vocabulary), the task goes to COO (orchestrator) as the fallback — the most versatile agent who can delegate.

## Consequences

- Classifier must be updated when new agent capabilities are added
- "Catch-all" to COO is intentional — COO can route to specialized agents
- Testing requires fixtures covering each agent type keyword set