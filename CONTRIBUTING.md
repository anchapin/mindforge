# Contributing to MindForge

Thank you for contributing to MindForge. This document covers everything you need
to know to get your first contribution in.

## Code of Conduct

By participating, you agree to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## Getting Started

### First-Time Setup

```bash
git clone https://github.com/alex/mindforge.git
cd mindforge
cp .env.example .env       # fill in OPENROUTER_API_KEY and FERNET_KEY
make setup                 # Python venv + frontend deps + Docker containers
make dev                   # start dev services with hot reload
make test                  # verify full test suite passes
```

### Reading the Spec

Before making any non-trivial change, read the relevant section of [SPEC.md](SPEC.md):
- Skill changes → Section 2.3
- Memory changes → Section 2.2
- Agent changes → Section 2.1
- UI changes → Section 2.7
- Infrastructure changes → Section 5.8

## Branching Strategy

| Branch | Purpose |
|---|---|
| `main` | Stable, always deployable |
| `feat/<name>` | New features |
| `fix/<name>` | Bug fixes |
| `skill/<name>` | Skill additions |
| `integration/<name>` | Integration additions |
| `docs/<name>` | Documentation only |

Branch from `main`, target `main`.

## Commit Message Format

Conventional Commits (required for all commits):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

| Type | When to use |
|---|---|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `test` | Test additions or fixes |
| `refactor` | Code restructure, no behavior change |
| `perf` | Performance improvement |
| `security` | Security fix or hardening |
| `chore` | Build, deps, CI |

Examples:
```
feat(skills): add linear-issue-creator skill
fix(memory): correct HMAC verification on semantic memory reads
docs(api): document /ready endpoint response shape
test(retriever): add hybrid search RRF unit test
```

## Running the Test Suite

```bash
make test              # full suite (unit + integration)
make lint              # ruff check + mypy type check
make fmt               # auto-format code

# Run only a subset
pytest backend/tests/unit -q
pytest backend/tests/unit/test_skill_graph_validation.py -q
```

## Adding a Skill

1. Create `backend/skills/skills/my-skill.yaml` (see SPEC.md Section 2.3 for schema)
2. Validate: `python -m backend.skills.registry validate backend/skills/skills/my-skill.yaml`
3. Add test in `backend/tests/unit/test_skill_graph_validation.py`
4. Add integration test in `backend/tests/integration/test_skill_execution.py`
5. Submit PR with `skill/<name>` branch

## Adding an Integration

1. Implement `BaseTool` in `backend/tools/<name>.py` (see SPEC.md Section 5.7.7)
2. Register in `backend/tools/registry.py`
3. Add fixtures in `backend/tests/fixtures/integrations/`
4. Add to `INTEGRATION_RATE_LIMITS` (SPEC.md Section 5.5)
5. Document auth method in `SECURITY.md`
6. Submit PR with `integration/<name>` branch

## Phase Contribution Process

MindForge is built in 4 phases (SPEC.md Sections 5.1–5.4). Contributions must
state which phase they target. Contributions requiring Phase 4 infrastructure
(Composio, full OAuth) will be accepted as PRs but held for the Phase 4 merge.

## Pull Request Review Criteria

PRs are reviewed for:
1. Correctness — does it do what it says?
2. Security — no credential leakage, no approval gate bypass, safe YAML loading
3. Testing — new code has tests
4. Spec compliance — changes are reflected in SPEC.md
5. Breaking change disclosure — skill schema or API changes flagged

Review timeline: acknowledgment within 48h, decision within 7 days.

## Labels

| Label | Meaning |
|---|---|
| `bug` | Confirmed bug |
| `enhancement` | New feature or improvement |
| `skill` | Skill-related change |
| `integration` | Integration-related change |
| `good first issue` | Suitable for new contributors |
| `security` | Security-sensitive change |
| `breaking` | Requires version bump |
| `docs` | Documentation only |

## Community SLA

| Commitment | Target |
|---|---|
| Issue acknowledgment | Within 48h |
| PR initial review | Within 7 days |
| Bug fix (confirmed) | Within 14 days |
| Security disclosure response | Within 48h |
| Good first issue guidance | Within 7 days |

**Contribution acceptance:** All contributions are welcome. Merging is not
guaranteed — contributions must pass review criteria (Section 5.11.8) and
align with the phase scope. Low-quality PRs (missing tests, no spec update,
breaking changes without disclosure) will be closed with guidance.

**Phase gates:** Phase 4 infrastructure contributions (Composio, full OAuth)
will be accepted as PRs but not merged until Phase 4 begins. Label with
`Phase 4` and `on-hold` to signal this.
