# MindForge Gap Analysis — Task Board
> Generated from SPEC.md gap analysis. 14 tasks across 3 phases.
> Created: 2026-05-14

## Phase 1 — Core Loop Close-Out (P0)

### [P0] task-1: Wire LangGraph SqliteSaver checkpointer — [#15](https://github.com/anchapin/mindforge/issues/15)
- **Agent:** backend | **Priority:** P0 | **Complexity:** high
- **Depends:** none
- **Files:** `backend/agents/supervisor.py`, `backend/pyproject.toml`
- **AC:** langgraph-checkpoint-sqlite in deps; SqliteSaver used (not MemorySaver fallback); test passes; Phase 1 exit criterion cleared

### [P0] task-2: Implement trigger_skill() three-stage chain — [#16](https://github.com/anchapin/mindforge/issues/16)
- **Agent:** backend | **Priority:** P0 | **Complexity:** high
- **Depends:** none
- **Files:** `backend/skills/trigger.py`, `backend/main.py`
- **AC:** explicit > keyword > intent priority; classify_intent LLM; SkillRegistry.load_all() on startup; test passes

### [P0] task-3: Wire skill executor into SupervisorRunner + draft-approve-continue — [#17](https://github.com/anchapin/mindforge/issues/17)
- **Agent:** backend | **Priority:** P0 | **Complexity:** very-high
- **Depends:** task-2
- **Files:** `backend/agents/supervisor.py`, `backend/skills/executor.py`, `backend/api/routes/tasks.py`
- **AC:** run_with_skill() callable; skill DAG routed to execute_skill(); draft at approval gate; POST /approve resumes DAG; test passes

### [P0] task-4: Implement clarification protocol (WS + API) — [#18](https://github.com/anchapin/mindforge/issues/18)
- **Agent:** backend | **Priority:** P0 | **Complexity:** medium
- **Depends:** none
- **Files:** `backend/api/routes/tasks.py`, `backend/api/websocket.py`, `backend/agents/supervisor.py`
- **AC:** POST /clarification endpoint; send_clarification_request() on ambiguity; context.constraint injected; test passes

---

## Phase 1 — Core Loop Close-Out (P1)

### [P1] task-5: Implement per-integration rate limiter — [#19](https://github.com/anchapin/mindforge/issues/19)
- **Agent:** backend | **Priority:** P1 | **Complexity:** medium
- **Depends:** none
- **Files:** `backend/tools/rate_limiter.py`, tool integrations
- **AC:** IntegrationRateLimiter per SPEC 5.5.2; all tool calls through integration_call(); test: 6 GitHub -> 5 pass, 1 queued

### [P1] task-6: Writing style learning (LLM extraction on approval) — [#20](https://github.com/anchapin/mindforge/issues/20)
- **Agent:** backend | **Priority:** P1 | **Complexity:** high
- **Depends:** task-3
- **Files:** `backend/memory/style.py`, `backend/api/routes/tasks.py`
- **AC:** LLM extraction on approval; update_writing_style(); edited draft also extracted; test passes

### [P1] task-7: UserPreference API + onboarding endpoint — [#21](https://github.com/anchapin/mindforge/issues/21)
- **Agent:** backend | **Priority:** P1 | **Complexity:** medium
- **Depends:** none
- **Files:** `backend/api/routes/preferences.py`, `backend/api/routes/onboarding.py`
- **AC:** GET/PUT /api/preferences; POST /api/onboarding; OnboardingWizard wired

### [P1] task-8: SkillLauncher wired to GET /api/skills — [#22](https://github.com/anchapin/mindforge/issues/22)
- **Agent:** frontend | **Priority:** P1 | **Complexity:** medium
- **Depends:** task-2
- **Files:** `backend/api/routes/skills.py`, `frontend/src/components/SkillLauncher.tsx`
- **AC:** GET /api/skills catalog; skill click -> POST /skills/{id}/run; SkillLauncher displays catalog

---

## Phase 2

### [P2] task-9: Wire all WebSocket messages at correct state transitions — [#23](https://github.com/anchapin/mindforge/issues/23)
- **Agent:** backend | **Priority:** P2 | **Complexity:** medium
- **Depends:** task-3
- **Files:** `backend/api/routes/tasks.py`, `backend/api/websocket.py`
- **AC:** All 8 WS message types (SPEC 2.5) sent at correct transitions; NotificationBell shows real counts; test passes

### [P2] task-10: Temporal service + actual workflows — [#24](https://github.com/anchapin/mindforge/issues/24)
- **Agent:** backend | **Priority:** P2 | **Complexity:** very-high
- **Depends:** none
- **Files:** `compose.yaml`, `backend/scheduler/temporal_app.py`, `backend/scheduler/workflows/`
- **AC:** Temporal in compose.yaml; email monitor workflow running; follow-up workflow running; startup test passes

---

## Phase 3

### [P3] task-11: LinearTool (Phase 1 per SPEC 5.1) — [#25](https://github.com/anchapin/mindforge/issues/25)
- **Agent:** backend | **Priority:** P3 | **Complexity:** high
- **Depends:** task-5
- **Files:** `backend/tools/integrations/linear.py`, `backend/tools/registry.py`
- **AC:** LinearTool with CRUD; registered; rate limited; test passes

### [P3] task-12: GET /api/usage budget endpoint + WS budget alerts — [#26](https://github.com/anchapin/mindforge/issues/26)
- **Agent:** backend | **Priority:** P3 | **Complexity:** low
- **Depends:** none
- **Files:** `backend/api/routes/usage.py`, `backend/api/websocket.py`
- **AC:** Usage endpoint; dashboard banner on approaching limit; WS alert sent; test passes

### [P3] task-13: Stripe webhook handler with HMAC verification — [#27](https://github.com/anchapin/mindforge/issues/27)
- **Agent:** backend | **Priority:** P3 | **Complexity:** medium
- **Depends:** none
- **Files:** `backend/api/routes/webhooks.py`, `backend/tools/integrations/stripe.py`
- **AC:** POST /webhooks/stripe with HMAC verification; billing anomaly -> draft approval; test passes

### [P3] task-14: GitHubTool.get_commits() pagination + date filtering — [#28](https://github.com/anchapin/mindforge/issues/28)
- **Agent:** backend | **Priority:** P3 | **Complexity:** medium
- **Depends:** task-5
- **Files:** `backend/tools/integrations/github.py`
- **AC:** Pagination through all pages; since=YYYY-MM-DD filtering; rate limit handling; test passes

---

## Dependency Graph

```
task-1 (checkpointer)  --> Phase 1 exit

task-2 (trigger_skill)  --> task-3 (skill executor) --> task-6 (style learning)
                                    |                  --> task-8 (skill launcher FE)
                                    --> task-9 (WS messages)
                                           |
task-5 (rate limiter)  --> task-11 (LinearTool) --> task-14 (GitHub pagination)
        |
        +--> task-10 (Temporal)
```

## Stats

| Phase | P0 | P1 | P2 | P3 | Total |
|---|---|---|---|---|---|
| Phase 1 | 4 | 4 | - | - | 8 |
| Phase 2 | - | - | 2 | - | 2 |
| Phase 3 | - | - | - | 4 | 4 |
| **Total** | **4** | **4** | **2** | **4** | **14** |
