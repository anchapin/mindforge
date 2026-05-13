<!-- /.github/PULL_REQUEST_TEMPLATE.md -->

## Description
Brief description of what this PR does and why.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Skill addition
- [ ] Integration addition
- [ ] Documentation
- [ ] Refactor
- [ ] Test improvement

## Phase Alignment
- [ ] Phase 1 — Core Loop
- [ ] Phase 2 — Multi-Agent + Skills
- [ ] Phase 3 — Proactive Execution
- [ ] Phase 4 — Composio + Production
- [ ] Cross-phase (affects all phases)

## Breaking Change
Does this PR change the skill YAML schema, API surface, or memory format?
- [ ] Yes — minor version bump required (see Section 5.10)
- [ ] No

## Testing
What testing was done?

- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual verification: _______________

## Checklist

- [ ] Code follows the style guidelines (run `make lint`)
- [ ] Self-review completed
- [ ] Comments added for complex logic
- [ ] All new integrations documented in `SECURITY.md`
- [ ] All new environment variables documented in `.env.example`
- [ ] If adding a skill: validated with `python -m backend.skills.registry validate`
- [ ] If changing memory layer: HMAC verification passes
