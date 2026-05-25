# ADR-004: Layer 3 Memory-Ratio Approval Gate

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Alex

## Context

MindForge agents use retrieved memory as context for LLM calls. A security concern arises: if an agent's output is stored as memory, and that memory is then used to prompt a subsequent LLM call, the memory content grows without bound (amplification).

Layer 3 of the integration security framework requires an approval gate when memory ratio > 0.5 (i.e., when >50% of the context window is retrieved memory rather than fresh task input).

## Decision

Draft-first workflow with mandatory human approval for high-memory-ratio invocations.

## Reasons

- **Bounded context**: When memory_ratio > 0.5, the fresh task context is <50% of what the LLM sees. This creates a "memory echo chamber" risk where agent conclusions areReinforced by its own prior outputs without fresh external signal.
- **Human review breakpoint**: Approval gate forces human to review what the agent concluded before that conclusion becomes the basis for more agent action.
- **Audit trail**: Draft state allows the human to see exactly what the agent plans to do before it does it.

## Implementation

1. Draft stored with `status=pending_approval`
2. Approval request sent to human (via WebSocket to dashboard)
3. Human reviews draft + memory content
4. On approval, agent proceeds to execute; on rejection, task is revised

## Consequences

- Approval gates introduce latency (human must be available)
- "Forced draft" mode for high-stakes integrations (stripe, send_email, github_push) — memory injection triggers forced draft regardless of ratio
- Agent cannot self-approve; a human must be in the loop