# Compound Init

Initialize this repository for compound engineering.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" init --target .
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" check --target .
```

Confirm that `.claude/settings.json` enables Claude Code agent teams with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, and use `.agent-loop/codex-parallel-contract.md` for the matching Codex or other-agent parallel workflow.
Also review `.agent-loop/harness-checklist.md`, `.agent-loop/readme-maintenance.md`, and `CODEBASE_MAP.md` so the project is navigable before adding MCP or LSP complexity.
The initialized project should be portable through `scripts/compound_orchestrator.py`, `scripts/verify.py`, `scripts/verify.ps1`, and `scripts/verify.sh`.
