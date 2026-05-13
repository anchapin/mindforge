# MindForge — Implementation Plan

> **Spec version:** Draft v0.1.0 (from `SPEC.md`)
> **Created:** 2026-05-13
> **Phases:** 4 (Phase 1 = Core Loop, Phase 2 = Multi-Agent+Skills, Phase 3 = Proactive, Phase 4 = Composio)
> **Estimated duration:** 10–14 weeks solo

---

## Overview

MindForge is a self-hosted multi-agent AI operating system — a local clone of surething.io.
Four role-specialized agents (COO, CMO, Researcher, Engineer) share persistent memory and
execute tasks through a skill graph with human approval gates.

This plan decomposes the SPEC into executable units, assigns them to AI coding agents,
and defines the delivery order.

---

## Phase Map

| Phase | Goal | Duration | Key Deliverables |
|---|---|---|---|
| **0 — Scaffold** | Project foundation, CI, repo init | 1 week | Directory layout, Docker compose, test infra, GitHub repo |
| **1 — Core Loop** | Single-agent demo, in-memory | 3–4 weeks | FastAPI + LangGraph single-agent, PGLite + ChromaDB, React dashboard |
| **2 — Multi-Agent** | 4-agent team, skills framework | 3–4 weeks | LangGraph supervisor, skill executor, WebSocket, draft-first workflow |
| **3 — Proactive** | 24/7 monitoring, Temporal | 2–3 weeks | Background workflows, email monitor, calendar, Stripe webhooks |
| **4 — Production** | Composio, OAuth, polish | 2–3 weeks | Full 864+ integrations, self-hosted Temporal cluster |

---

## Phase 0 — Scaffold (Foundation)

### 0.1 Directory Structure

```
mindforge/
├── SPEC.md
├── IMPLEMENTATION_PLAN.md
├── README.md
├── CONTRIBUTING.md
├── AGENTS.md
├── LICENSE
├── .env.example
├── Makefile
├── pyproject.toml
├── backend/
│   ├── pyproject.toml
│   ├── main.py
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── supervisor.py        # LangGraph supervisor (Phase 2)
│   │   ├── coo.py               # Phase 2
│   │   ├── cmo.py               # Phase 2
│   │   ├── researcher.py         # Phase 2
│   │   ├── engineer.py           # Phase 2
│   │   └── routing.py           # Phase 1 (keyword classifier)
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── store.py             # SharedMemoryStore facade
│   │   ├── semantic.py          # ChromaDB (Phase 1)
│   │   ├── episodic.py          # PGLite (Phase 1)
│   │   ├── style.py             # WritingProfile (Phase 1)
│   │   ├── sanitizer.py         # Prompt injection defense (Phase 2)
│   │   └── embeddings.py        # Ollama embeddings (Phase 1)
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── registry.py          # Skill loader/executor
│   │   ├── validator.py         # Graph validation
│   │   └── skills/
│   │       ├── github-daily-summary.yaml
│   │       └── subscription-refund.yaml
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── registry.py          # ToolRegistry
│   │   ├── base.py             # BaseTool abstract class
│   │   └── integrations/       # Per-integration tools
│   │       ├── github.py
│   │       ├── stripe.py
│   │       └── email.py
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── temporal_app.py     # Temporal client
│   │   └── tasks.py            # Proactive workflows (Phase 3)
│   ├── db/
│   │   ├── __init__.py
│   │   ├── schema.sql          # PGLite schema
│   │   ├── models.py           # Pydantic models
│   │   └── migrations/          # Alembic migrations
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── tasks.py
│   │   │   ├── memories.py
│   │   │   ├── skills.py
│   │   │   └── integrations.py
│   │   ├── websocket.py        # WS manager + protocol
│   │   └── deps.py             # FastAPI dependencies
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── router.py           # Tiered inference router
│   │   ├── inference.py        # LLM call with circuit breaker
│   │   ├── cost_tracker.py     # OpenRouter spend tracking
│   │   └── prompts.py          # PromptBuilder
│   ├── exceptions.py            # Exception taxonomy (E_RETRY/ESCALATE/LOG/PANIC)
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       ├── unit/
│       │   ├── test_classify_task_type.py
│       │   ├── test_skill_graph_validation.py
│       │   ├── test_safe_yaml_loading.py
│       │   ├── test_hmac_tamper_detection.py
│       │   ├── test_fernet_round_trip.py
│       │   ├── test_scrub_sensitive_fields.py
│       │   └── test_circuit_breaker.py
│       ├── integration/
│       │   ├── test_task_lifecycle.py
│       │   ├── test_chroma_semantic_memory.py
│       │   └── test_pglite_episodic_memory.py
│       └── fixtures/
│           └── skills/
│               ├── valid-github-daily-summary.yaml
│               └── invalid-cycle-skill.yaml
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── tailwind.config.js
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── ChatInterface.tsx
│   │   │   ├── TaskTracker.tsx
│   │   │   ├── DraftReview.tsx
│   │   │   ├── MemoryViewer.tsx
│   │   │   ├── SkillLauncher.tsx
│   │   │   └── ClarificationModal.tsx
│   │   ├── stores/
│   │   │   ├── taskStore.ts     # Zustand
│   │   │   └── notificationStore.ts
│   │   └── lib/
│   │       ├── api.ts           # TanStack Query
│   │       └── websocket.ts     # WS client + reconnect
│   └── tests/
│       └── unit/
│           └── DraftReview.test.tsx
├── compose.yaml                 # Docker services
├── Dockerfile.backend
├── Dockerfile.frontend
├── .github/
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── release.yml
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md
│       ├── feature_request.md
│       ├── skill_submission.md
│       └── good_first_issue.md
└── scripts/
    ├── backup.sh
    ├── restore.sh
    └── export.sh
```

### 0.2 AI Coding Agent Workstreams

**Scaffold agent** (Tier 1 — foundational, sequential):
1. Create all directories
2. Write `backend/pyproject.toml` (all dependency pins from SPEC.md §5.12)
3. Write `frontend/package.json` (all dependency pins from SPEC.md §5.12)
4. Write `Dockerfile.backend`, `Dockerfile.frontend`
5. Write `compose.yaml` (Phase 1 scope: backend + chroma + pglite)
6. Write `.env.example`
7. Write `Makefile` (setup, dev, test, lint, fmt, logs, clean)
8. Write `backend/db/schema.sql` (all tables from SPEC.md §4)
9. Write `backend/exceptions.py` (E_RETRY/ESCALATE/LOG/PANIC taxonomy)
10. Write `backend/tests/conftest.py` (pytest fixtures)

**Backend Core agent** (Tier 2 — Phase 1 backend, sequential after scaffold):
1. `backend/main.py` — FastAPI app with lifespan, health endpoints
2. `backend/llm/inference.py` — OpenRouter client, fallback chain, circuit breaker
3. `backend/llm/router.py` — Tiered inference (LOCAL/cloud_fast/cloud_heavy)
4. `backend/llm/cost_tracker.py` — Budget guard
5. `backend/memory/embeddings.py` — Ollama nomic-embed-text
6. `backend/memory/semantic.py` — ChromaDB wrapper
7. `backend/memory/episodic.py` — PGLite episodic memory
8. `backend/memory/style.py` — WritingProfile CRUD
9. `backend/memory/store.py` — SharedMemoryStore facade
10. `backend/agents/routing.py` — classify_task_type() keyword rules

**Backend API agent** (Tier 2 — Phase 1 API, parallel with Backend Core):
1. `backend/api/deps.py` — FastAPI dependency injection
2. `backend/api/routes/tasks.py` — CRUD endpoints
3. `backend/api/routes/memories.py` — Memory read/write
4. `backend/api/websocket.py` — WS connection manager, protocol messages

**Frontend agent** (Tier 2 — Phase 1 dashboard, sequential after scaffold):
1. `frontend/src/stores/taskStore.ts` — Zustand task state
2. `frontend/src/lib/api.ts` — TanStack Query fetchers
3. `frontend/src/lib/websocket.ts` — WS client with reconnect
4. `frontend/src/components/ChatInterface.tsx`
5. `frontend/src/components/TaskTracker.tsx`
6. `frontend/src/App.tsx`

**Skill Author agent** (Tier 3 — Phase 2 skills, sequential after backend core):
1. `backend/skills/registry.py` — Skill loader with safe_load validation
2. `backend/skills/validator.py` — validate_skill_graph()
3. `backend/skills/skills/github-daily-summary.yaml`
4. `backend/skills/skills/subscription-refund.yaml`
5. Unit tests for skill registry and validation

**Integration agent** (Tier 3 — Phase 1 integrations, sequential after backend core):
1. `backend/tools/base.py` — BaseTool abstract class
2. `backend/tools/registry.py` — ToolRegistry
3. `backend/tools/integrations/github.py` — GitHub API client
4. `backend/tools/integrations/stripe.py` — Stripe client
5. `backend/tools/integrations/email.py` — IMAP/SMTP client

---

## Phase 1 — Core Loop (3–4 weeks)

### Exit Criteria (automated tests)

| Criterion | Test |
|---|---|
| Task enters system → agent retrieves memories → output stored | `test_task_stores_episodic_on_completion` |
| Agent resumes after restart (checkpointer) | `test_langgraph_checkpointer_resume` |
| Draft-first pauses and resumes on approval | `test_draft_approval_flow_blocks_until_approved` |
| Skill version pinning at invocation | `test_skill_version_pinned_at_invocation` |

### Critical Path

1. **LLM Router** — gpt-4o → claude-3.5 → gemini-2 fallback chain
2. **SharedMemoryStore** — read (semantic + episodic + style) → inject into prompt
3. **Task State Machine** — pending → running → draft → executing → completed
4. **WebSocket** — agent events → dashboard → approval → agent
5. **LangGraph Checkpointing** — SQLite persistence, task resume after restart

### Security Gates (Phase 1)

- [ ] `yaml.safe_load()` on all skill YAML (SPEC.md §3b.1)
- [ ] `scrub()` on all log output and WS messages (SPEC.md §3b.6)
- [ ] Fernet token encryption at rest (SPEC.md §4.3)
- [ ] HMAC signing on semantic memory writes (SPEC.md §3b.8)
- [ ] `allowed_agents` / `permissions` scoping on integrations (SPEC.md §3b.2)

---

## Phase 2 — Multi-Agent + Skills (3–4 weeks)

### Exit Criteria

| Criterion | Test |
|---|---|
| Multi-agent task routes to correct specialist | `test_supervisor_routes_to_correct_agent` |
| Draft-first pauses and resumes on approval | `test_draft_approval_flow_blocks_until_approved` |
| Skill with branching DAG completes end-to-end | `test_branching_skill_execution` |
| Skill version pinning: mid-execution update doesn't affect running task | `test_skill_version_pinned_at_invocation` |
| Clarification request surfaces to user before execution | `test_clarification_request_before_action` |

### Critical Path

1. **LangGraph Supervisor** — 4-agent routing with role specialization
2. **Skill Executor** — branching DAG with approval gates, retry, timeout
3. **trigger_skill()** — keyword → explicit → intent classifier chain
4. **Writing Style Learning** — LLM extraction from approved drafts
5. **Clarification Protocol** — WebSocket round-trip for ambiguous tasks

---

## Phase 3 — Proactive Execution (2–3 weeks)

### Exit Criteria

| Criterion | Test |
|---|---|
| Temporal worker handles task failure with retry and DLQ | `test_temporal_retry_on_transient_failure` |
| Webhook delivers Stripe event → agent processes → action | `test_stripe_webhook_triggers_temporal_workflow` |
| Background task runs without manual trigger | `test_proactive_monitoring_runs_automatically` |

---

## Phase 4 — Production (2–3 weeks)

### Exit Criteria

| Criterion | Test |
|---|---|
| Agent runs 7 days without manual restart | `test_seven_day_continuous_run` |
| Draft-first completes on 5 different skill types | `test_draft_first_completes_all_skill_types` |

---

## Test Coverage Targets

| Layer | Coverage |
|---|---|
| Backend unit tests | 70% line coverage |
| Backend integration tests | 50% line coverage |
| Skill validation + security primitives | 95% line coverage |
| Frontend unit tests | 60% component coverage |
| Key paths (submit→complete, draft→approve) | 100% E2E |

---

## Version & Release

| Event | Version |
|---|---|
| Phase 0 (scaffold complete) | 0.1.0-alpha |
| Phase 1 shipped | 0.2.0-alpha |
| Phase 2 shipped | 0.3.0-alpha |
| Phase 3 shipped | 0.4.0-alpha |
| Phase 4 shipped | 1.0.0-alpha |

Git tag on each phase exit: `git tag -a v<version> -m "Phase X complete"`

---

## AI Coding Agent Instructions

Each agent should:
1. Read SPEC.md §relevant-section before implementing
2. Write tests BEFORE code (TDD from SPEC.md exit criteria)
3. Run `make lint` and `make test` before completing
4. Update SPEC.md only if changing a public contract (skill YAML schema, API surface, memory format)
5. Never hardcode credentials — always from environment variables
6. Follow the exception taxonomy (E_RETRY/ESCALATE/LOG/PANIC)

**AGENTS.md** (`/home/alex/Projects/mindforge/AGENTS.md`) is the primary navigation
document for AI agents. Read it before starting any work.

---

*Plan generated: 2026-05-13*
*Based on: SPEC.md Draft v0.1.0*
