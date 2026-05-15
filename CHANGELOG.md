# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

---

## [0.2.1] — 2026-05-15

Stabilization release. Closes the P0 bug bucket discovered after Phase 1
shipped, plus the structural fixes surfaced by the Wave 2 code review.

### Added

- `EmailSendTool` for SMTP delivery via `aiosmtplib`, registered as
  `email_send` and routed through the per-integration rate limiter
  ([#42], [#65]).
- `StripeTool.execute(action="refund")` for issuing refunds via
  `POST /v1/refunds`; supports partial refunds, reasons, and metadata
  ([#43], [#66]).
- TanStack Router foundation: `/tasks`, `/skills`, `/memory`,
  `/preferences` routes with lazy-loaded code-split chunks and
  active-link `aria-current=page` ([#48], [#67]).
- `OnboardingWizard` mounted as a first-run modal in `RootLayout`,
  driven by the new `/api/preferences.onboarding_completed` flag.
  Complete and Skip both POST to the backend; failure leaves the
  modal open so the user can retry ([#46], [#68], [#70], [#72], [#73]).
- Global `NotificationBell` and `ClarificationModal` mounted in
  `RootLayout`. WS frames (`draft_ready`, `task_failed`,
  `task_completed`, `clarification_request`) now drive a bounded
  in-memory notification store and a clarification queue
  ([#47], [#69]).
- `POST /api/onboarding/skip` endpoint for dismiss-without-write
  ([#72], [#73]).
- `submitClarification`, `submitOnboarding`, `submitOnboardingSkip`,
  `fetchPreferences` typed helpers in `frontend/src/lib/api.ts`.
- `backend/skills/validator.py` — single source of truth for skill
  graph validation, accepting both bare-graph and full-skill input
  shapes ([#45], [#64]).
- `backend/db/migrate._apply_inplace_column_additions()` — idempotent
  in-place column adds for evolving schemas without losing data on
  alpha installs ([#73]).
- `register_all_tools()` is now called at FastAPI lifespan startup so
  the integrations test endpoint can resolve tools by name in
  production (was a registry empty in real deployments) ([#71]).
- New CI workflow scaffolding lives under `.github/workflows/` with
  the existing `ci.yml`; release pipeline tracked separately
  ([#54] — pending).

### Changed

- `BaseTool.validate_auth(self) -> bool` is now
  `validate_auth(self, token: str | None = None) -> bool`. All four
  built-in tools (Stripe, GitHub, Email, Linear) updated. Linear
  keeps `api_key` as an alias for backward compatibility ([#44],
  [#63]).
- `POST /api/integrations/{id}/test` is now a real probe — looks up
  the tool, decrypts the stored token, calls `validate_auth(token)`.
  Returns `{success, probed, message}` so callers can distinguish
  "no probe wired" from "credential rejected" ([#44], [#63]).
- `subscription-refund.yaml` now references the canonical `stripe_api`
  tool name (was `stripe_refund_api`, which had no implementation)
  ([#43], [#66]).
- `vite.config.ts` now exposes `host: true` + `strictPort: true` and
  resolves `@/*` → `src/*` to match `tsconfig.json` paths ([#39],
  [#48], [#61], [#67]).
- `Makefile`'s `make dev` is now compose-only; new `make dev-host`
  preserves the host-machine HMR escape hatch ([#39], [#61]).
- `_HIGH_STAKES_ACTIONS` set extended with the dotted canonical
  forms `email_send.send` and `stripe_api.refund` so SPEC §3b.8
  Layer-3 approval gates fire on memory-dominated proposals
  ([#42], [#43], [#65], [#66], [#71]).

### Fixed

- `check_chroma()` / `check_temporal()` / `check_ollama()` honor
  `CHROMA_HOST` / `TEMPORAL_HEALTH_URL` / `OLLAMA_BASE_URL` env vars
  instead of hardcoded `localhost`. `/ready` no longer falsely reports
  services unhealthy under docker compose ([#41], [#59]).
- Missing `Dockerfile.frontend.dev` (referenced by `compose.yaml` but
  never created) now exists; `docker compose --profile dev up`
  succeeds ([#39], [#61]).
- All four routes in `backend/api/routes/integrations.py` now declare
  `Depends(db_dep)`. Pre-fix every request 422'd because FastAPI saw
  `db` as an unannotated query parameter ([#38], [#60]).
- SQL targets the canonical `integration` (singular) table everywhere
  — `integrations.py`, `onboarding.py`, and supporting tests. Pre-fix
  every query against the legacy plural raised `OperationalError`
  silently ([#38], [#60], [#72], [#73]).
- `backend/api/routes/integrations.py` now JSON-encodes
  `permissions` / `allowed_agents` instead of `str(list)` so
  reads can deserialize them back into actual lists ([#38], [#60]).
- `StripeTool.validate_auth` and `GitHubTool.validate_auth` now accept
  the real stored token instead of literal placeholder strings.
  Returns `False` on 401/4xx/connect-error/missing-token; previously
  returned `True` on 401 (Stripe) or `False` always (GitHub) ([#44],
  [#63]).
- `execute_node` in the skill executor now (a) lists available tools
  in the system prompt (`## Available tools`) so the LLM can plan
  around them, and (b) renders prior nodes' scratch state in the
  user prompt so multi-node DAGs no longer degenerate into
  independent single-shot calls. Removed the misleading
  `"currently a stub"` comment ([#40], [#62]).
- Two divergent copies of `validate_skill_graph` consolidated into
  `backend/skills/validator.py`. Cycle detection now uses the
  iterative DFS + `on_stack` set everywhere; the route's old
  recursive `has_path` produced false positives on diamond DAGs
  ([#45], [#64]).
- `writing_profile` schema gains `created_at` (the existing route
  INSERTed it but the schema never declared it — silent runtime
  failure on every onboarding) ([#72], [#73]).
- `OnboardingWizard.handleComplete` now actually POSTs to
  `/api/onboarding`; pre-fix it just dismissed the modal so no
  data was ever persisted, and the gate would never re-fire
  thanks to the localStorage flag ([#72], [#73]).
- `WSMessageHandler` lifted from `TaskTracker` into `RootLayout` so
  notifications fire on every route, not just `/tasks` ([#47],
  [#69]).
- High-stakes-action contract tests tightened to require the
  canonical dotted names (no `OR` legacy-name fallback). Catches
  regressions where a tool refactor silently drops the SPEC §3b.8
  gate ([#71]).

### Security

- The integrations test endpoint no longer ships an "always-true"
  stub — bad credentials now surface to the user as
  `"X credential rejected by API"` ([#44], [#63]).
- `permissions` / `allowed_agents` round-trip through proper JSON
  encoding so the agent-to-integration scoping in SPEC §3b.2 isn't
  silently broken by `str(list)` artefacts ([#38], [#60]).
- High-stakes tools (`email_send`, `stripe_api refund`) now register
  with the SPEC §3b.8 Layer-3 approval gate by their canonical
  dotted action names. Memory-dominated proposals to send mail or
  refund a charge will pause for human approval ([#42], [#43], [#65],
  [#66]).

---

## [0.2.0-alpha] — 2026-05-14

Phase 1 close-out. The full multi-agent loop now runs end-to-end:
LangGraph supervisor routes tasks to specialist agents, skills execute
through a DAG with approval gates, and integrations are rate-limited
per-app.

### Added

- LangGraph `StateGraph` supervisor with role-specialized agents
  (COO, CMO, Researcher, Engineer); routing via `classify_task_type`
  keyword classifier ([#9]).
- Skill registry, executor, trigger pipeline, plus two production
  skills (`subscription-refund`, `distill-your-own-skill`) ([#8]).
- `trigger_skill()` three-stage chain: explicit name → keyword →
  intent classifier ([#16], [#31]).
- Skill executor wired into `SupervisorRunner`; draft-approve-continue
  flow with mid-execution checkpoint ([#17], [#30], [#31]).
- Clarification protocol — `POST /api/tasks/{id}/clarification` +
  `clarification_request` WS message ([#18], [#31]).
- Per-integration rate limiter using `asyncio.Semaphore`; GitHub /
  Stripe / Linear / email tools all routed through `integration_call`
  ([#19], [#33], [#36]).
- Writing-style learning — LLM extraction on draft approval; updates
  `WritingProfile` with extracted tone/length/signoff fields ([#20],
  [#33]).
- `UserPreference` API (`GET/PUT /api/preferences`) and
  `POST /api/onboarding` endpoint ([#21], [#34]).
- `SkillLauncher` wired to `GET /api/skills` catalog with
  success/failure counts ([#22]).
- Full WebSocket message protocol — 8 message types fire at correct
  task state transitions ([#23], [#33]).
- Temporal proactive workflow engine (gated behind `ENABLE_TEMPORAL`);
  `EmailMonitorWorkflow` shipped ([#24], [#37]).
- `LinearTool` (Phase 1 integration) — list/create/update/get issues
  via GraphQL ([#25], [#36]).
- `GET /api/usage` budget endpoint + WS budget alerts ([#26]).
- Stripe webhook handler with HMAC-SHA256 signature verification;
  billing anomaly above threshold triggers draft approval ([#27]).
- `GitHubTool.get_commits()` pagination + date filtering ([#28]).
- `LangGraph SqliteSaver` checkpointer wired so tasks survive process
  restarts (Phase 1 exit criterion) ([#15], [#29]).
- Hybrid BM25 + vector RRF retrieval for semantic memory ([#5],
  [#12]).
- Layer 2 + Layer 3 prompt-injection defense; `sanitize_for_memory`
  scrub + memory-context approval gate amplification ([#3], [#10]).
- Phase 2 frontend components — `ClarificationModal`,
  `MemoryViewer`, `SkillLauncher`, `OnboardingWizard`,
  `NotificationBell` ([#4], [#11]).
- 23 Phase 1 exit-criteria integration tests ([#6], [#13]).
- Project scaffolding files — Makefile, LICENSE, CHANGELOG,
  PRIVACY.md, GOVERNANCE.md, ISSUE_TEMPLATE/, PR template
  ([#7], [#14]).

---

## [0.1.0] — 2026-05-13

### Added

- Hybrid inference router with local Ollama + cloud OpenRouter tiers (SPEC 5.7.1)
- Unified tool interface and ToolRegistry (SPEC 5.7.7)
- Dockerfiles for backend and frontend (SPEC 5e.1)
- Complete compose.yaml with health checks and profiles (SPEC 5e.2)
- Structured logging with structlog (SPEC 5e.5)
- Health endpoints `/health` and `/ready` (SPEC 5e.4)
- Backup/restore scripts (SPEC 5e.7)
- Alembic migration setup for PGLite (SPEC 5e.6)
- Skill registry with YAML validation (SPEC 2.3)
- SharedMemoryStore facade (SPEC 2.2)
- Supervisor, COO, CMO, Researcher, Engineer agents (SPEC 2.1)
- Draft-first approval workflow (SPEC 2.7.3)
- HMAC-signed semantic memory (SPEC 3b.6)
- GLiGuard prompt injection defense (SPEC 3b.8)

[Unreleased]: https://github.com/anchapin/mindforge/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/anchapin/mindforge/compare/v0.2.0-alpha...v0.2.1
[0.2.0-alpha]: https://github.com/anchapin/mindforge/compare/v0.1.0...v0.2.0-alpha
[0.1.0]: https://github.com/anchapin/mindforge/releases/tag/v0.1.0

[#3]: https://github.com/anchapin/mindforge/issues/3
[#4]: https://github.com/anchapin/mindforge/issues/4
[#5]: https://github.com/anchapin/mindforge/issues/5
[#6]: https://github.com/anchapin/mindforge/issues/6
[#7]: https://github.com/anchapin/mindforge/issues/7
[#8]: https://github.com/anchapin/mindforge/pull/8
[#9]: https://github.com/anchapin/mindforge/pull/9
[#10]: https://github.com/anchapin/mindforge/pull/10
[#11]: https://github.com/anchapin/mindforge/pull/11
[#12]: https://github.com/anchapin/mindforge/pull/12
[#13]: https://github.com/anchapin/mindforge/pull/13
[#14]: https://github.com/anchapin/mindforge/pull/14
[#15]: https://github.com/anchapin/mindforge/issues/15
[#16]: https://github.com/anchapin/mindforge/issues/16
[#17]: https://github.com/anchapin/mindforge/issues/17
[#18]: https://github.com/anchapin/mindforge/issues/18
[#19]: https://github.com/anchapin/mindforge/issues/19
[#20]: https://github.com/anchapin/mindforge/issues/20
[#21]: https://github.com/anchapin/mindforge/issues/21
[#22]: https://github.com/anchapin/mindforge/issues/22
[#23]: https://github.com/anchapin/mindforge/issues/23
[#24]: https://github.com/anchapin/mindforge/issues/24
[#25]: https://github.com/anchapin/mindforge/issues/25
[#26]: https://github.com/anchapin/mindforge/issues/26
[#27]: https://github.com/anchapin/mindforge/issues/27
[#28]: https://github.com/anchapin/mindforge/issues/28
[#29]: https://github.com/anchapin/mindforge/pull/29
[#30]: https://github.com/anchapin/mindforge/pull/30
[#31]: https://github.com/anchapin/mindforge/pull/31
[#33]: https://github.com/anchapin/mindforge/pull/33
[#34]: https://github.com/anchapin/mindforge/pull/34
[#36]: https://github.com/anchapin/mindforge/pull/36
[#37]: https://github.com/anchapin/mindforge/pull/37
[#38]: https://github.com/anchapin/mindforge/issues/38
[#39]: https://github.com/anchapin/mindforge/issues/39
[#40]: https://github.com/anchapin/mindforge/issues/40
[#41]: https://github.com/anchapin/mindforge/issues/41
[#42]: https://github.com/anchapin/mindforge/issues/42
[#43]: https://github.com/anchapin/mindforge/issues/43
[#44]: https://github.com/anchapin/mindforge/issues/44
[#45]: https://github.com/anchapin/mindforge/issues/45
[#46]: https://github.com/anchapin/mindforge/issues/46
[#47]: https://github.com/anchapin/mindforge/issues/47
[#48]: https://github.com/anchapin/mindforge/issues/48
[#54]: https://github.com/anchapin/mindforge/issues/54
[#59]: https://github.com/anchapin/mindforge/pull/59
[#60]: https://github.com/anchapin/mindforge/pull/60
[#61]: https://github.com/anchapin/mindforge/pull/61
[#62]: https://github.com/anchapin/mindforge/pull/62
[#63]: https://github.com/anchapin/mindforge/pull/63
[#64]: https://github.com/anchapin/mindforge/pull/64
[#65]: https://github.com/anchapin/mindforge/pull/65
[#66]: https://github.com/anchapin/mindforge/pull/66
[#67]: https://github.com/anchapin/mindforge/pull/67
[#68]: https://github.com/anchapin/mindforge/pull/68
[#69]: https://github.com/anchapin/mindforge/pull/69
[#70]: https://github.com/anchapin/mindforge/pull/70
[#71]: https://github.com/anchapin/mindforge/pull/71
[#72]: https://github.com/anchapin/mindforge/issues/72
[#73]: https://github.com/anchapin/mindforge/pull/73
