# Soak Tests

Long-running stability tests for MindForge. Soak tests run the full stack continuously to detect memory leaks, restart loops, and integration drift.

## Running a Soak Test

```bash
# Full 7-day soak test
./scripts/soak_test.sh

# Dry-run (verifies setup, produces 1-cycle report)
DRY_RUN=1 ./scripts/soak_test.sh

# Smoke soak (2-hour, fast skill mix)
DURATION_SECONDS=7200 INTERVAL_SECONDS=300 ./scripts/soak_test.sh
```

Results are written to `${RUN_DIR}/events.jsonl` and `${RUN_DIR}/report.md`.

## PASS Criteria

| # | Criterion | Threshold |
|---|---|---|
| 1 | Zero process restarts | no `container_restart` events |
| 2 | Bounded memory growth | final/initial ratio < 1.5x |
| 3 | Skill diversity | >= 5 distinct skills triggered |

## Generating a Report

```bash
python3 scripts/soak_report.py ~/.mindforge-soak/run-<id>/events.jsonl \
    --run-id <id> \
    --out docs/soak-tests/run-<id>.md
```

## Recorded Results

- `docs/soak-tests/` — Published soak test reports
- `~/.mindforge-soak/run-<id>/` — Raw event logs (keep for debugging)