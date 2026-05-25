# ADR-001: LangGraph Supervisor Pattern

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Alex

## Context

MindForge requires a multi-agent orchestration system to route tasks to specialized agents (COO, CMO, Researcher, Engineer). We evaluated three approaches:

1. **LangGraph** — Directed graph with state management, designed for agent workflows
2. **AutoGen** — Microsoft framework for multi-agent conversation
3. **CrewAI** — Role-based multi-agent framework

## Decision

We chose **LangGraph** with a supervised routing pattern.

## Reasons

- **Explicit state**: LangGraph's graph state is explicit dict, not implicit conversation context. Enables persistence, time-travel debugging, and checkpointer-based resumability.
- **Checkpointer support**: Built-in SQLite checkpointer allows agent runtime to resume mid-workflow after restarts (critical for 24/7 proactive operation).
- **Supervisor pool**: Pre-compiled graph instances cached in a pool reduce first-request latency from ~3s to ~200ms (#143).
- **Tool calling**: Native integration with BaseTool implementations via structured output.
- **No imposed role semantics**: Unlike CrewAI, LangGraph doesn't impose "manager/agent" role semantics — our supervisor pool owns the routing logic.

AutoGen's group chat requires all agents to be online simultaneously. MindForge's human-in-the-loop approval model is incompatible with that assumption.

## Consequences

- Supervisor pool must be initialized at startup (added to lifespan)
- Checkpointer SQLite DB requires DATA_DIR writable
- Graph state schema must be versioned for migrations