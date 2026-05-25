# Two-Round Cross-Review Protocol

`compound-cross-review` is a two-round review contract, not a one-note ritual.

For each task, keep these files under `docs/cross-reviews/<task-id>/`:

1. `round-1-review.md`
2. `round-1-response.md`
3. `round-2-review.md`
4. `round-2-response.md`
5. `final-acceptance.md`

Codex reviews Claude-authored work, Claude addresses comments, Codex reviews again, and Claude addresses the second round. For Codex-authored work, invert the reviewer and author tools. Stop after two rounds unless the user explicitly asks for more.

For planning gates, each review and response should cover all six artifacts:

- `prd.html`
- `planning.html`
- `spec.html`
- `test-cases.html`
- `architecture.html`
- `users.html`
