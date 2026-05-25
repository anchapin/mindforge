# Project Harness Checklist

Use this checklist when setting up or reviewing the Claude/Codex/agent harness for coding, writing, research, documentation, or mixed projects.

## Foundation

- [ ] One DRI owns settings, permissions, marketplace/plugin updates, and `CLAUDE.md` conventions.
- [ ] Root `CLAUDE.md` is short: big picture, navigation pointers, and critical gotchas.
- [ ] Subdirectory `CLAUDE.md` files capture local build, test, lint, and naming conventions.
- [ ] Developers start Claude Code in the subdirectory they are changing.
- [ ] `CODEBASE_MAP.md` points to top-level areas and deeper local context.
- [ ] `README.md` is current, reader-friendly, and includes the managed README maintenance policy.

## Automation

- [ ] `.claude/settings.json` denies generated, vendored, build, coverage, secret, and dependency paths.
- [ ] Hooks handle automatic checks or improvement prompts instead of relying on memory.
- [ ] Stop hook proposes `CLAUDE.md` or durable-memory updates when a session learns something reusable.
- [ ] Verification entrypoint exists and is scoped enough to avoid full-suite overuse.
- [ ] `scripts/verify.py`, `scripts/verify.ps1`, and `scripts/verify.sh` work on the platforms the team uses.

## Skills And Plugins

- [ ] Repeated task-specific expertise lives in skills, not root `CLAUDE.md`.
- [ ] Skills are path-scoped by placing them in the relevant subtree when possible.
- [ ] The baseline setup is packaged as a plugin so new engineers get it on day one.

## Code Intelligence And Integrations

- [ ] LSP is planned or installed for typed languages where grep is too noisy.
- [ ] MCP servers are added only after the context layer, skills, hooks, and ownership are healthy.
- [ ] Internal MCP integrations have an owner, auth model, and failure mode.

## Maintenance

- [ ] Harness review happens every 3-6 months and after major model releases.
- [ ] Dead instructions and obsolete hooks are removed.
- [ ] README updates remove obsolete information, keep still-true information, add new content, and reorganize the narrative.
- [ ] Repeated failures become docs, tests, hooks, or skills.
