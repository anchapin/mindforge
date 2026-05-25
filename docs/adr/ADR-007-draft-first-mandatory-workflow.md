# ADR-007: Draft-First Workflow as Mandatory

**Status:** Accepted
**Date:** 2026-05-13
**Deciders:** Alex

## Context

MindForge agents can take external actions (send emails, push to GitHub, issue refunds). These must not happen automatically — a human must review and approve before execution.

## Decision

Draft-first workflow is **mandatory, not optional** for all external actions.

## Reasons

- **Safety**: Any code that causes an external action without going through draft → user_approval → execute state transition is a security violation (per AGENTS.md rule #2).
- **Auditability**: Every external action has a human-reviewed draft on record
- **Reversibility**: Approval can be withheld or modified before irreversible action is taken

## Workflow

1. Agent produces a **draft** (proposed action + rationale)
2. Draft stored with `status=pending_approval`
3. Human reviews draft via dashboard
4. Human **approves** or **rejects** (with feedback)
5. On approval, agent **executes** the action
6. Execution result is stored; human is notified of completion

## Consequences

- No external action can occur without human in the loop
- Dashboard must support draft review UI
- Agent cannot "proceed automatically" for high-stakes actions — explicit approval required
- Low-stakes internal actions (memory writes, analysis) may proceed without approval