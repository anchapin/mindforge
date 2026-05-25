# backend/skills — Skill System

## Purpose

Skill registry, trigger matching, executor, validator, and YAML skill definitions for MindForge's skill-based agent workflow system.

## Local Commands

- **Validate a skill YAML**: `python -m backend.skills.registry validate backend/skills/skills/<skill>.yaml`
- **Test skill loading**: `python -c "from backend.skills.registry import get_registry; r = get_registry(); print(r.list_skills())"`
- **List all skills**: `python -c "from backend.skills.registry import get_registry; r = get_registry(); [print(s.name, s.enabled) for s in r.list_skills()]"`
- **Run skill tests**: `cd backend && pytest tests/unit/test_skill*.py -v`

## Local Conventions

- **YAML only**: Skills use `yaml.safe_load()` — no Python objects in YAML (`!!python/object` tags are rejected)
- **Naming**: Skill filenames match skill names: `github-pr-review.yaml` → skill `github-pr-review`
- **Tool names in skills**: Must match exactly `ToolRegistry.list_names()` (e.g., `github_api`, `stripe_api`, `email_send`)
- **Approval required**: Any node performing an external action must set `approval_required: true`
- **At least one end node**: Every skill execution graph must have at least one node with `type: end`

## Skill YAML Schema (from SPEC.md §2.3)

```yaml
name: skill-name
description: Use when ...
trigger:
  type: keyword|event|schedule
  keywords: [keyword1, keyword2]  # for type=keyword
nodes:
  - id: start
    type: start
  - id: process
    type: action
    tool: tool_name
    approval_required: false
  - id: end
    type: end
edges:
  - from: start
    to: process
  - from: process
    to: end
```

## Gotchas

- **Circular edges rejected**: Skill validator checks for cycles; skills with cycles fail validation
- **Tool not registered → silent failure**: If a skill references a tool not in `register_all_tools()`, the tool lookup fails at execution time, not at registration
- **Skill hot-reload**: Skills are loaded at startup; changes require restart (no runtime reload in Phase 1)

## Local Skills

Path-scoped skills for specialized workflows are in:

```text
backend/skills/.claude/skills/<skill-name>/SKILL.md
```