# Compound Cross Review

Use this for the required two-round cross-tool review protocol.

Steps:

1. Inspect active ownership with `compound-ownership-status`.
2. Review only the authoring agent's diff or paths named by the lead.
3. Cover all six planning artifacts when this is a planning gate: `prd.html`, `planning.html`, `spec.html`, `test-cases.html`, `architecture.html`, and `users.html`.
4. Lead with findings ordered by severity.
5. Write each stage:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" cross-review --target . --task-id TASK_ID --reviewer-tool codex --author-tool claude --stage round-1-review --summary "Round 1 findings..."
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" cross-review --target . --task-id TASK_ID --reviewer-tool claude --author-tool codex --stage round-1-response --summary "Claude addressed round 1..."
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" cross-review --target . --task-id TASK_ID --reviewer-tool codex --author-tool claude --stage round-2-review --summary "Round 2 findings..."
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" cross-review --target . --task-id TASK_ID --reviewer-tool claude --author-tool codex --stage round-2-response --summary "Claude addressed round 2..."
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" cross-review --target . --task-id TASK_ID --reviewer-tool codex --author-tool claude --stage final-acceptance --summary "Accepted after two rounds."
```

Stop after two rounds unless the user explicitly asks for another loop.
