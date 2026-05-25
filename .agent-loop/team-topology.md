# Compound Agent Team Topology

Use this file as the shared operating contract for Claude Code agent teams and Codex parallel-agent runs.

## Default Team

| Role | Claude Code Teammate Type | Codex Role | Scope | Output |
| --- | --- | --- | --- | --- |
| Lead Integrator | lead session | local lead | Plan, assign, synthesize, integrate | Final diff and summary |
| PRD Agent | task-specific teammate | worker | Product requirements contract | `prd.html` |
| Users Agent | task-specific teammate | worker | User roles and workflows | `users.html` |
| Architect | `compound-architect` | explorer | Existing patterns, design, risks | Architecture notes |
| Planning Agent | task-specific teammate | worker | Delivery plan | `planning.html` |
| Spec Agent | task-specific teammate | worker | Behavior, state, data, validation, and acceptance contract | `spec.html` |
| Test Case Agent | `compound-test-runner` | worker/explorer | Happy paths, edge cases, errors, performance, workflows | `test-cases.html` |
| Implementer | task-specific teammate | worker | Bounded work product with owned files | Patch, draft, or handoff |
| Test Runner | `compound-test-runner` | worker/explorer | Verification strategy and execution | Test results |
| Reviewer | `compound-reviewer` | explorer/reviewer | Correctness, security, tests, product risk | Findings |
| Claude Cross-Tool Reviewer | `compound-cross-tool-reviewer` | n/a | Review Codex-authored changes | Cross-tool findings |
| Codex Cross-Tool Reviewer | n/a | `codex-cross-tool-reviewer` skill | Review Claude-authored changes | Cross-tool findings |
| Compound Writer | lead or reviewer | local lead | Durable learning | Pattern, decision, failure, or compound note |

## When To Use A Team

Use a team for:

- dependency-aware planning across PRD, users, architecture, planning, spec, and tests
- research and review
- competing debugging hypotheses
- new modules with separable ownership
- writing or research sections with separable claims, sources, or review lanes
- cross-layer work where frontend, backend, and tests can be owned separately

Do not use a team for:

- tiny fixes
- sequential migrations
- same-file edits
- work without a clear verification path

## Claude Code Team Rules

- `.claude/settings.json` must set `env.CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` to `"1"`.
- Ask Claude to create an agent team in natural language; Claude creates the runtime team config itself.
- Reuse plugin or project agent definitions as teammate types.
- Start with 3-5 teammates and give each teammate a scoped task.
- Use `compound-cross-tool-reviewer` when reviewing work authored by Codex or another agent runtime.
- Keep runtime team files under `~/.claude/teams/` untouched; they are managed by Claude Code.

## Codex Parallel-Agent Rules

- The lead Codex session owns decomposition, final synthesis, and integration.
- Spawn agents only for independent work that materially advances the task.
- Give every spawned agent: role, goal, read/write scope, output artifact, and verification responsibility.
- Workers that edit files must have disjoint ownership.
- Explorer/reviewer agents should be read-only unless explicitly assigned a patch.
- The lead should not redo delegated work; integrate results and fill gaps.
- Use the `codex-cross-tool-reviewer` skill when reviewing work authored by Claude Code or another agent runtime.
- Planning runs should parallelize independent drafts, then serialize integration, `spec.html`, `test-cases.html`, two-round review, and final acceptance.

## Ownership Claims

Before edits, claim files, directories, drafts, or artifacts:

```bash
python scripts/compound_orchestrator.py claim --tool codex --agent codex-worker --task-id TASK --paths src/payments.py tests/test_payments.py --intent "Implement retry handling"
```

The claim fails if another active Claude or Codex agent already owns an overlapping path. Release claims when done:

```bash
python scripts/compound_orchestrator.py release --tool codex --agent codex-worker --task-id TASK
```

## Shared Handoff

Every team run should leave a note in `docs/compound/` with:

- task id
- team members and scopes
- files owned by each agent
- ownership conflicts and resolutions
- verification run
- review findings
- cross-tool review result
- two-round review responses and final acceptance
- lessons promoted to patterns, decisions, or failures
