#!/usr/bin/env bash
# scripts/soak_test.sh -- Phase 4 7-day continuous-run harness (#58).
#
# Drives a `docker compose --profile prod` MindForge stack with a rotating
# mix of skill triggers, polls /health for liveness, samples container
# memory via `docker stats`, and appends each event to a JSONL log that
# `scripts/soak_report.py` turns into a markdown PASS/FAIL report.
#
# Defaults match SPEC §5.4 (7 days, 30-min cycle). Override via env vars
# for fast smoke runs in CI / local sanity checks.
#
# Env vars:
#   API_BASE              default http://127.0.0.1:8000
#   INTERVAL_SECONDS      default 1800   (30 min)
#   DURATION_SECONDS      default 604800 (7 days)
#   RUN_DIR               default ${HOME}/.mindforge-soak/run-<timestamp>
#   SKILL_LIST            default refund,calendar-conflict,distill,github-summary,email-followup
#                         (>= 5 skills satisfies AC #3 in #58)
#   COMPOSE_BACKEND       default backend  (docker compose service name)
#   DRY_RUN               if "1", print the plan + write a 1-line event
#                         log, then exit 0 -- used by CI smoke tests.
#
# AGENTS.md compliance:
#   - Rule 7: never logs API tokens; only event metadata.
#   - Rule 6: respects ENABLE_TEMPORAL / ENABLE_COMPOSIO via the running
#     stack -- the harness itself is phase-agnostic.

set -uo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-1800}"
DURATION_SECONDS="${DURATION_SECONDS:-604800}"
RUN_ID="${RUN_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_DIR="${RUN_DIR:-${HOME}/.mindforge-soak/run-${RUN_ID}}"
SKILL_LIST="${SKILL_LIST:-refund,calendar-conflict,distill,github-summary,email-followup}"
COMPOSE_BACKEND="${COMPOSE_BACKEND:-backend}"
DRY_RUN="${DRY_RUN:-0}"

mkdir -p "${RUN_DIR}"
EVENT_LOG="${RUN_DIR}/events.jsonl"

# ---------- helpers ----------

emit() {
  # emit '{"key":"value", ...}' -> appends to event log with ISO timestamp
  local payload="$1"
  local ts
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '{"ts":"%s",%s}\n' "${ts}" "${payload}" >> "${EVENT_LOG}"
}

probe_health() {
  local start_ms end_ms latency_ms ok status
  start_ms=$(($(date +%s%N)/1000000))
  status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${API_BASE}/health" 2>/dev/null || echo "000")
  end_ms=$(($(date +%s%N)/1000000))
  latency_ms=$((end_ms - start_ms))
  if [ "${status}" = "200" ]; then ok="true"; else ok="false"; fi
  emit "\"kind\":\"health_probe\",\"ok\":${ok},\"status_code\":${status},\"latency_ms\":${latency_ms}"
}

trigger_skill() {
  local skill="$1"
  local body status ok
  body=$(printf '{"description":"soak-test trigger for %s","skill_id":"%s"}' "${skill}" "${skill}")
  status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 \
    -H 'content-type: application/json' \
    -d "${body}" "${API_BASE}/api/tasks/" 2>/dev/null || echo "000")
  if [ "${status}" = "200" ] || [ "${status}" = "201" ]; then ok="true"; else ok="false"; fi
  emit "\"kind\":\"skill_trigger\",\"skill\":\"${skill}\",\"ok\":${ok},\"status_code\":${status}"
}

scrape_metrics() {
  # Optional /metrics scrape -- gracefully degrades while #52 is open.
  local status
  status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "${API_BASE}/metrics" 2>/dev/null || echo "000")
  if [ "${status}" = "200" ]; then
    emit "\"kind\":\"metrics_scrape\",\"ok\":true,\"status_code\":${status}"
  else
    emit "\"kind\":\"metrics_scrape\",\"ok\":false,\"reason\":\"metrics_endpoint_not_implemented\""
  fi
}

sample_container_stats() {
  # Captures memory_mb / memory_pct / cpu_pct for the backend container.
  # Gracefully no-ops if docker is unavailable (operator may run the
  # harness against a remote stack via API_BASE override).
  if ! command -v docker >/dev/null 2>&1; then return 0; fi
  local stats
  stats=$(docker stats --no-stream --format '{{.MemUsage}}|{{.MemPerc}}|{{.CPUPerc}}' "${COMPOSE_BACKEND}" 2>/dev/null || true)
  if [ -z "${stats}" ]; then return 0; fi
  local mem_usage mem_pct cpu_pct mem_mb
  mem_usage=$(echo "${stats}" | cut -d'|' -f1 | awk '{print $1}')
  mem_pct=$(echo "${stats}"   | cut -d'|' -f2 | tr -d '%')
  cpu_pct=$(echo "${stats}"   | cut -d'|' -f3 | tr -d '%')
  # Convert mem_usage (e.g. "312.5MiB" / "1.5GiB") to MB.
  case "${mem_usage}" in
    *GiB) mem_mb=$(awk -v v="${mem_usage%GiB}" 'BEGIN{printf "%.1f", v*1024}') ;;
    *MiB) mem_mb=$(awk -v v="${mem_usage%MiB}" 'BEGIN{printf "%.1f", v}') ;;
    *KiB) mem_mb=$(awk -v v="${mem_usage%KiB}" 'BEGIN{printf "%.3f", v/1024}') ;;
    *)    mem_mb="0" ;;
  esac
  emit "\"kind\":\"container_stats\",\"container\":\"${COMPOSE_BACKEND}\",\"memory_mb\":${mem_mb},\"memory_pct\":${mem_pct},\"cpu_pct\":${cpu_pct}"
}

detect_restart() {
  # Compare the current backend container start time against the previous
  # snapshot; emit container_restart when it changes.
  if ! command -v docker >/dev/null 2>&1; then return 0; fi
  local cur prev_file prev
  cur=$(docker inspect -f '{{.State.StartedAt}}' "${COMPOSE_BACKEND}" 2>/dev/null || true)
  [ -z "${cur}" ] && return 0
  prev_file="${RUN_DIR}/.backend_started_at"
  if [ -f "${prev_file}" ]; then
    prev=$(cat "${prev_file}")
    if [ "${cur}" != "${prev}" ]; then
      emit "\"kind\":\"container_restart\",\"container\":\"${COMPOSE_BACKEND}\",\"started_at\":\"${cur}\""
    fi
  fi
  echo "${cur}" > "${prev_file}"
}

# ---------- main loop ----------

emit "\"kind\":\"harness_start\",\"run_id\":\"${RUN_ID}\",\"interval_seconds\":${INTERVAL_SECONDS},\"duration_seconds\":${DURATION_SECONDS}"

if [ "${DRY_RUN}" = "1" ]; then
  emit "\"kind\":\"dry_run\",\"api_base\":\"${API_BASE}\",\"skill_list\":\"${SKILL_LIST}\""
  emit "\"kind\":\"harness_stop\",\"run_id\":\"${RUN_ID}\",\"duration_seconds\":0,\"reason\":\"dry_run\""
  echo "DRY_RUN: wrote ${EVENT_LOG}"
  exit 0
fi

IFS=',' read -ra SKILLS <<< "${SKILL_LIST}"
SKILL_COUNT=${#SKILLS[@]}
START_EPOCH=$(date +%s)
END_EPOCH=$((START_EPOCH + DURATION_SECONDS))
CYCLE=0

while [ "$(date +%s)" -lt "${END_EPOCH}" ]; do
  detect_restart
  probe_health
  sample_container_stats
  scrape_metrics
  # Rotate through the skill list one per cycle.
  SKILL="${SKILLS[$((CYCLE % SKILL_COUNT))]}"
  trigger_skill "${SKILL}"
  CYCLE=$((CYCLE + 1))
  sleep "${INTERVAL_SECONDS}"
done

NOW_EPOCH=$(date +%s)
emit "\"kind\":\"harness_stop\",\"run_id\":\"${RUN_ID}\",\"duration_seconds\":$((NOW_EPOCH - START_EPOCH))"
echo "Soak run complete. Generate report:"
echo "  python3 scripts/soak_report.py ${EVENT_LOG} --run-id ${RUN_ID} --out ${RUN_DIR}/report.md"
