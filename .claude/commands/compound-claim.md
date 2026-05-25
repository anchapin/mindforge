# Compound Claim

Claim files, directories, drafts, or artifacts before editing so agent runtimes do not collide.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" claim --target . --tool claude --agent "$USER" --task-id TASK_ID --paths path/to/file.py --intent "Describe planned edit"
```

If the claim fails, stop and report the existing owner. Do not edit overlapping files until the lead narrows scope or releases the claim.
