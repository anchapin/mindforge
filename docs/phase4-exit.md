# Phase 4 exit criterion -- 7-day continuous-run soak test

Per **SPEC §5.4** the Phase 4 exit gate is:

> Agent runs for 7 days without manual restart. Webhook events processed within 5s. Draft-first workflow completes end-to-end on 5 different skill types.

Issue [#58](https://github.com/anchapin/mindforge/issues/58) tracks the
implementation. This document records the **PASS criteria**, the
**operator runbook**, and the **first successful run evidence**.

## PASS criteria

A soak run is considered green when **all three** of the following hold:

| # | Criterion | Threshold | Source signal |
|---|---|---|---|
| 1 | **Zero process restarts** | 0 `container_restart` events | `docker inspect -f '{{.State.StartedAt}}' backend` polled each cycle |
| 2 | **Bounded memory growth** | `final_memory_mb / initial_memory_mb < 1.5` | `docker stats --no-stream` polled each cycle |
| 3 | **5 distinct skill types triggered** | `len(distinct_skill_ids) >= 5` | `POST /api/tasks/` per cycle, rotating through `SKILL_LIST` |

Each is checked independently in `scripts/soak_report.py`
(`check_no_restarts`, `check_bounded_memory`, `check_skill_diversity`)
and surfaced as a row in the rendered markdown report.

## Runbook -- one-shot operator workflow

```bash
# 1. Bring up the production stack.
docker compose --profile prod up -d

# 2. Wait for the backend to report healthy.
until curl -fs http://127.0.0.1:8000/health >/dev/null; do sleep 5; done

# 3. Launch the harness in the background. Defaults to 7 days @ 30 min.
nohup ./scripts/soak_test.sh > soak.log 2>&1 &

# 4. After the run completes (or any time mid-run), generate the report:
python3 scripts/soak_report.py \
  ~/.mindforge-soak/run-<RUN_ID>/events.jsonl \
  --run-id <RUN_ID> \
  --out ~/.mindforge-soak/run-<RUN_ID>/report.md
```

### Fast smoke (CI / pre-flight)

```bash
DRY_RUN=1 ./scripts/soak_test.sh
```

`DRY_RUN=1` writes a single-line event log without making any API calls
or sleeping the cycle interval. Used by the pytest smoke test
(`backend/tests/integration/test_soak_test_harness.py`) so the harness
contract stays in lockstep with `soak_report.py`.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `API_BASE` | `http://127.0.0.1:8000` | Backend root URL (override for remote stacks) |
| `INTERVAL_SECONDS` | `1800` (30 min) | Cycle period |
| `DURATION_SECONDS` | `604800` (7 days) | Total runtime |
| `RUN_DIR` | `~/.mindforge-soak/run-<id>` | Where `events.jsonl` is written |
| `SKILL_LIST` | `refund,calendar-conflict,distill,github-summary,email-followup` | Comma-separated skill_id rotation. **Must be >= 5 to satisfy AC #3.** |
| `COMPOSE_BACKEND` | `backend` | Docker compose service name for stats/restart polling |
| `DRY_RUN` | `0` | Set to `1` for the CI smoke path |

## Known degradations (operator-visible in the report)

- **`/metrics` endpoint missing.** [#52](https://github.com/anchapin/mindforge/issues/52)
  ships the Prometheus endpoint; until it lands, the harness records
  `metrics_scrape: ok=false reason=metrics_endpoint_not_implemented`
  and the report's "Degradation notes" section enumerates the misses.
- **Skill catalogue smaller than `SKILL_LIST`.** Only 3 skills exist on
  `main` today (`subscription-refund`, `calendar-conflict`,
  `distill-your-own-skill`). The other two entries in the default
  `SKILL_LIST` (`github-summary`, `email-followup`) are placeholders
  for skills the maintainer can either author before the run or strike
  from the env override. The harness will record `skill_trigger:
  ok=false` for any skill_id the supervisor doesn't resolve.

## Run evidence

> The first successful 7-day run goes here. Maintainer: paste the
> rendered `report.md` (or a link to it) below this line and tag the
> commit `phase4-exit-evidence`.

_(no successful run captured yet — populated post-merge by operator)_
