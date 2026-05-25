# Compound Deliverables Check

Check that the planning contracts, two-round review artifacts, verification evidence, README freshness, and compound learning are ready for handoff.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compound_orchestrator.py" check --target . --task-id TASK_ID
```

If this fails, address missing artifacts instead of declaring the work complete.
