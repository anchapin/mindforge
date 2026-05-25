# Path-Scoped Skill Template

Place this under the relevant subtree:

```text
services/payments/.claude/skills/payments-deploy/SKILL.md
```

Use a path-scoped skill when the expertise applies to one module or task type and would bloat root `CLAUDE.md`.

```markdown
---
name: payments-deploy
description: Use when deploying or reviewing deployment changes for the payments service.
---

# Payments Deploy

## When To Use

Use for payments deployment, rollback, and post-deploy validation.

## Required Context

- Local `CLAUDE.md`
- Service runbook
- Recent deployment notes

## Workflow

1. Check branch and diff scope.
2. Run focused tests.
3. Verify migration/backfill risk.
4. Prepare deploy or rollback notes.
5. Record any durable learning in `docs/`.
```
