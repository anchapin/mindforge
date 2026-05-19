# MindForge (Planar Nexus) Development Tasks

## Specification Summary
**Original Requirements**: Build a self-hosted, single-user clone of surething.io's core functionality — a multi-agent AI team with shared persistent memory, proactive 24/7 execution, skills system, dashboard UI, and key integrations.
**Technical Stack**: Python (FastAPI, LangGraph), React (TypeScript, Vite, Tailwind), PGLite, ChromaDB, Temporal.
**Target Timeline**: Phase 4: v1.0.1 Patch (Current Sprint)

## Development Tasks

### [ ] Task 1: Complete JSON recovery implementation for all agents
**Description**: Refactor CMO, Researcher, and Engineer agents to use the `parse_with_recovery` utility already implemented in `coo.py`.
**Acceptance Criteria**: 
- CMO, Researcher, and Engineer agents no longer fail silently on malformed JSON.
- `parse_with_recovery` is the shared entry point for LLM response parsing.
- Unit tests verify recovery from common LLM markdown-wrapping artifacts.

**Files to Create/Edit**:
- `backend/agents/cmo.py`
- `backend/agents/researcher.py`
- `backend/agents/engineer.py`

**Reference**: Issue #2: Agent JSON fragility

### [ ] Task 2: Wire agent identity to tool execution in supervisor
**Description**: Update `specialist_node` in `supervisor.py` to pass the `agent_role` as `agent_identity` when calling tools, enabling the permission checks in `BaseTool`.
**Acceptance Criteria**: 
- `BaseTool.execute` receives the correct `agent_identity`.
- Integration tests confirm that unauthorized agents are blocked from calling restricted tools.

**Files to Create/Edit**:
- `backend/agents/supervisor.py`
- `backend/tools/base.py`

**Reference**: Issue #3: Tool permission enforcement

### [ ] Task 3: Global data-testid injection for E2E stability
**Description**: Add `data-testid` attributes to all primary interactive components (Buttons, Inputs, Modals, Nav items) to stabilize Playwright E2E tests.
**Acceptance Criteria**: 
- Primary UI elements have unique, stable `data-testid` attributes.
- Playwright tests updated to use these IDs instead of fragile CSS/text selectors.
- `frontend/src/components/` files updated.

**Files to Create/Edit**:
- `frontend/src/components/ChatInterface.tsx`
- `frontend/src/components/TaskTracker.tsx`
- `frontend/src/components/DraftReview.tsx`
- `frontend/src/components/SkillLauncher.tsx`

**Reference**: User Hint: data-testid injection

### [ ] Task 4: Refactor classify_task_type to shared routing module
**Description**: Consolidate duplicated classification logic from `store.py` and `supervisor.py` into `backend/agents/routing.py`.
**Acceptance Criteria**: 
- Single source of truth for task classification.
- No regression in routing accuracy.

**Files to Create/Edit**:
- `backend/agents/routing.py`
- `backend/memory/store.py`
- `backend/agents/supervisor.py`

**Reference**: Issue #4: Duplicate classify_task_type

### [ ] Task 5: Migrate PGLite to aiosqlite (Async I/O)
**Description**: Replace synchronous `sqlite3` calls with `aiosqlite` in `EpisodicMemoryStore` and `WritingProfileStore` to prevent blocking the event loop.
**Acceptance Criteria**: 
- All database operations are awaited and non-blocking.
- Existing memory tests pass with async implementation.

**Files to Create/Edit**:
- `backend/memory/episodic.py`
- `backend/memory/style.py`

**Reference**: Issue #5: Sync SQLite in async

### [ ] Task 6: Implement SupervisorRunner Pool
**Description**: Initialize a pool of pre-compiled `SupervisorRunner` instances at startup to avoid expensive graph compilation per request.
**Acceptance Criteria**: 
- `SupervisorRunnerPool` initialized in FastAPI lifespan.
- Tasks are executed by acquiring a runner from the pool.
- Performance metrics show reduced task startup latency.

**Files to Create/Edit**:
- `backend/agents/supervisor.py`
- `backend/api/routes/tasks.py`
- `backend/main.py`

**Reference**: Issue #6: SupervisorRunner not reused

### [ ] Task 7: E2E Stability - Implement retry logic for transient integration failures
**Description**: Wrap external integration calls (GitHub, Stripe) in retry logic with exponential backoff.
**Acceptance Criteria**: 
- Transient network errors (5xx, timeouts) do not crash the task.
- `BaseTool` handles retries using the configured `retry_config`.

**Files to Create/Edit**:
- `backend/tools/base.py`
- `backend/tools/integrations/github.py`
- `backend/tools/integrations/stripe.py`

**Reference**: User Hint: E2E stability

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
