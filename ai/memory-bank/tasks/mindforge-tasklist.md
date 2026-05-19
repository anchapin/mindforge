# MindForge (Planar Nexus) Development Tasks

## Specification Summary
**Original Requirements**: Build a self-hosted, single-user clone of surething.io's core functionality — a multi-agent AI team with shared persistent memory, proactive 24/7 execution, skills system, dashboard UI, and key integrations.
**Technical Stack**: Python (FastAPI, LangGraph), React (TypeScript, Vite, Tailwind), PGLite, ChromaDB, Temporal.
**Target Timeline**: Phase 4: v1.0.1 Patch (Current Sprint)

## Development Tasks

### [x] Task 1: Complete JSON recovery implementation for all agents
**Description**: Refactor CMO, Researcher, and Engineer agents to use the `parse_with_recovery` utility already implemented in `coo.py`.
**Status**: COMPLETED - All specialist agents now use `parse_with_recovery`.

### [x] Task 2: Wire agent identity to tool execution in supervisor
**Description**: Update `specialist_node` in `supervisor.py` to pass the `agent_role` as `agent_identity` when calling tools, enabling the permission checks in `BaseTool`.
**Status**: COMPLETED - Agent identity and integration configs are now propagated to tool execution.

### [x] Task 3: Global data-testid injection for E2E stability
**Description**: Add `data-testid` attributes to all primary interactive components (Buttons, Inputs, Modals, Nav items) to stabilize Playwright E2E tests.
**Status**: COMPLETED - data-testid attributes injected across core React components.

### [x] Task 4: Refactor classify_task_type to shared routing module
**Description**: Consolidate duplicated classification logic from `store.py` and `supervisor.py` into `backend/agents/routing.py`.
**Status**: COMPLETED - Routing logic centralized and fixed word boundary matching.

### [x] Task 5: Migrate PGLite to aiosqlite (Async I/O)
**Description**: Replace synchronous `sqlite3` calls with `aiosqlite` in `EpisodicMemoryStore` and `WritingProfileStore` to prevent blocking the event loop.
**Status**: COMPLETED - Verified full async I/O for SQLite stores.

### [x] Task 6: Implement SupervisorRunner Pool
**Description**: Initialize a pool of pre-compiled `SupervisorRunner` instances at startup to avoid expensive graph compilation per request.
**Status**: COMPLETED - Pool initialized in main.py and used in tasks API.

### [x] Task 7: E2E Stability - Implement retry logic for transient integration failures
**Description**: Wrap external integration calls (GitHub, Stripe) in retry logic with exponential backoff.
**Status**: COMPLETED - Exponential backoff with jitter implemented in BaseTool.

## Phase 4: Soak Test Preparation (Next Sprint)
### [x] Task 8: Author `github-summary` skill
- **Goal**: Create a skill that fetches latest GitHub activity and generates a summary.
- **Status**: COMPLETED - `github-summary.yaml` authored and validated.

### [x] Task 9: Author `email-followup` skill
- **Goal**: Create a skill that drafts a follow-up email for a specific task.
- **Status**: COMPLETED - `email-followup.yaml` authored and validated.

### [ ] Task 10: Execute 7-day soak test harness
- **Goal**: Run `scripts/soak_test.sh` and generate `report.md`.
- **AC**: Pass all 3 criteria (No restarts, bounded memory, 5+ skills).


## Quality Requirements
- [ ] All code changes must pass `make lint` and `make test`.
- [ ] New functionality must be covered by unit or integration tests.
- [ ] No background processes in any commands - NEVER append `&`.
- [ ] Mobile responsive design required for UI changes.
- [ ] Include Playwright screenshot testing: `./qa-playwright-capture.sh http://localhost:8000 public/qa-screenshots`.

## Technical Notes
**Development Stack**: FastAPI, LangGraph, React, Tailwind, PGLite, ChromaDB.
**Special Instructions**: Follow SPEC.md Section 3b for security mandates (HMAC, Safe YAML, Scrubbing).
**Timeline Expectations**: v1.0.1 Patch release target: End of Week.
