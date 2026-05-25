# Task Brief: Issue #157 — Track Uncommitted Changes Requiring Separate Review

## Goal

Organize all uncommitted files into a clear PR grouping, create the branch and PRs, and close issue #157 once all are merged.

## Context

Git status shows 27 untracked files. These were likely created by previous agent sessions but never committed. The issue describes 5 key groups:
1. Agent workflow docs (AGENTS.md, CLAUDE.md, README.md, STRATEGY.md, CODEBASE_MAP.md)
2. Architecture decision records (docs/adr/)
3. Planning contracts (prd.html, spec.html, planning.html, users.html, test-cases.html, architecture.html, architecture.excalidraw)
4. Test files (backend/tests/unit/test_linear_tool.py)
5. Schema changes (backend/db/schema.sql — not currently visible as untracked)
6. Agent loop harness (.agent-loop/, .claude/)
7. Skill config (backend/skills/CLAUDE.md, backend/tools/CLAUDE.md)
8. Scripts (scripts/compound_orchestrator.py, verify.py, verify.sh, verify.ps1)

Note: backend/db/schema.sql is NOT in the untracked list. It may have been committed already.

## Definition Of Done

- [ ] PR created for each logical group
- [ ] All PRs merged to main
- [ ] Issue #157 closed
- [ ] Compound note written at docs/compound/2026-05-25-uncommitted-changes-issue-157.md

## PR Groups

### PR 1: Compound Loop Harness
**Scope:** Agent workflow infrastructure
**Files:**
- .agent-loop/
- .claude/
- scripts/compound_orchestrator.py
- scripts/verify.py
- scripts/verify.sh
- scripts/verify.ps1

**Branch:** `feat/compound-loop-harness`

**Verification:** `python scripts/verify.py` passes

---

### PR 2: Planning Contracts
**Scope:** Six planning contract artifacts (required per AGENTS.md process)
**Files:**
- prd.html
- planning.html
- spec.html
- test-cases.html
- users.html
- architecture.html
- architecture.excalidraw

**Branch:** `feat/planning-contracts`

**Verification:** All 7 files exist and are non-empty

---

### PR 3: Architecture Decision Records
**Scope:** ADRs documenting key decisions
**Files:**
- docs/adr/ADR-001-langgraph-supervisor-pattern.md
- docs/adr/ADR-002-chromadb-pglite-split.md
- docs/adr/ADR-003-keyword-task-classification.md
- docs/adr/ADR-004-layer3-memory-approval-gate.md
- docs/adr/ADR-005-async-write-queue-circuit-breakers.md
- docs/adr/ADR-006-sqlite-checkpointer-persistence.md
- docs/adr/ADR-007-draft-first-mandatory-workflow.md

**Branch:** `feat/architecture-decision-records`

**Verification:** All 7 ADRs exist, each has Status, Context, Decision, Consequences

---

### PR 4: Agent Documentation Refresh
**Scope:** Updated agent-facing documentation
**Files:**
- AGENTS.md
- CLAUDE.md
- STRATEGY.md
- CODEBASE_MAP.md
- backend/skills/CLAUDE.md
- backend/tools/CLAUDE.md
- docs/patterns/
- docs/brainstorms/

**Branch:** `feat/agent-documentation-refresh`

**Verification:** AGENTS.md and CLAUDE.md are consistent and non-empty

---

### PR 5: Test File
**Scope:** Add test for Linear tool
**Files:**
- backend/tests/unit/test_linear_tool.py

**Branch:** `feat/test-linear-tool`

**Verification:** `pytest backend/tests/unit/test_linear_tool.py` passes

---

## Agent Lanes

| Lane | Scope | Owned Files | Output |
|---|---|---|---|
| Lead | Synthesis and final integration | All | Final grouping and summary |
| Worker | Create branches, PRs, handle any conflicts | N/A | Git operations |
| Review | Per-PR review of each group | Read-only | Findings |

## Risks

- **Risk:** Some files may be stale or duplicate content
- **Mitigation:** Review each group before committing; discard or merge if redundant

- **Risk:** PRs may have merge conflicts if other work lands on main
- **Mitigation:** Create PRs in sequence, monitor CI, resolve quickly

- **Risk:** issue #157 body may be incomplete about what exists
- **Mitigation:** Cross-reference git status output and issue description