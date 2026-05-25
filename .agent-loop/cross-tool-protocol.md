# Cross-Tool Conflict And Review Protocol

Use this protocol whenever Claude Code, Codex, or another agent runtime may work in the same repository.

## Conflict Prevention

1. Every editing agent claims its intended files or directories before editing.
2. Claims live in `.agent-loop/coordination/ownership.json`.
3. A claim fails when it overlaps another active claim from a different agent or tool.
4. The lead integrator resolves conflicts by narrowing scopes, releasing old claims, or serializing the work.
5. Agents release claims after their patch is integrated, abandoned, or handed off.

## Cross-Tool Review

- Claude Code uses `compound-cross-tool-reviewer` to review Codex-authored changes.
- Codex uses `codex-cross-tool-reviewer` to review Claude-authored changes.
- Cross-review findings and responses are written to `docs/cross-reviews/<task-id>/`.
- The required stages are `round-1-review.md`, `round-1-response.md`, `round-2-review.md`, `round-2-response.md`, and `final-acceptance.md`.
- A task involving both tools should not finish until both review rounds and author responses are complete.
- Stop after two rounds unless the user explicitly asks for more.
- Planning reviews must cover `prd.html`, `planning.html`, `spec.html`, `test-cases.html`, `architecture.html`, and `users.html`.

## Commands

```bash
python scripts/compound_orchestrator.py claim --tool codex --agent codex-worker --task-id TASK --paths src/foo.py
python scripts/compound_orchestrator.py ownership-status --target .
python scripts/compound_orchestrator.py cross-review --target . --task-id TASK --reviewer-tool codex --author-tool claude --stage round-1-review --summary "Round 1 findings."
python scripts/compound_orchestrator.py cross-review --target . --task-id TASK --reviewer-tool claude --author-tool codex --stage round-1-response --summary "Author addressed round 1."
python scripts/compound_orchestrator.py release --tool codex --agent codex-worker --task-id TASK
```
