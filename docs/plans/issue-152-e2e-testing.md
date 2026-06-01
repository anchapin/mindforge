# Task Brief: Issue #152 — E2E Test Suite

## Goal

Add E2E tests, integration tests for missing flows, and concurrent load tests. Close issue #152 once all tasks are complete and CI passes.

## Definition Of Done

- [ ] Playwright E2E setup added to project
- [ ] E2E test for critical user flows (task creation → approval → execution)
- [ ] Integration test for calendar-conflict.yaml full execution graph
- [ ] Concurrent read/write load test for SharedMemoryStore
- [ ] Soak test results recorded to docs/
- [ ] `make test` passes locally
- [ ] CI passes on all PRs
- [ ] Issue #152 closed

## PR Groups

### PR 1: Playwright E2E Setup + Calendar Conflict Integration Test
**Scope:**
- Add Playwright to frontend test dependencies
- Add `backend/tests/integration/test_calendar_conflict_execution.py` — full skill execution graph test
- Add `frontend/tests/e2e/` — E2E test setup

**Branch:** `test/e2e-setup`

### PR 2: Concurrent SharedMemoryStore Load Test
**Scope:**
- Add `backend/tests/integration/test_memory_store_concurrent.py` — concurrent read/write stress test
- Verify thread-safety of SharedMemoryStore

**Branch:** `test/concurrent-memory-store`

### PR 3: Soak Test Docs
**Scope:**
- Record soak test run results to docs/
- Verify soak_test.sh and soak_report.py work end-to-end

**Branch:** `test/soak-docs`

## Risks

- **Risk:** Playwright setup may conflict with existing Vitest
- **Mitigation:** Keep Vitest for unit/integration component tests; Playwright only for E2E browser flows

- **Risk:** Calendar-conflict skill execution may require real credentials
- **Mitigation:** Use mock integration clients where possible

- **Risk:** Concurrent test may be flaky
- **Mitigation:** Use deterministic sequencing and sufficient retry logic