# ADR-0001 — Composio Cloud Integration

- **Status:** Accepted (spike — production wiring tracked in #57, soak in #58)
- **Date:** 2026-05-14
- **Deciders:** @anchapin (maintainer)
- **Issue:** [#56](https://github.com/anchapin/mindforge/issues/56)
- **Phase:** 4 (gated; AGENTS.md Rule 6 / SPEC §5.4)

## Context

MindForge Phase 1–3 ships with four direct integrations (Gmail IMAP/SMTP,
GitHub, Linear, Stripe). SPEC §1, §5.4, and §5.12 commit Phase 4 to
**Composio Cloud** as the umbrella provider for the remaining 864+
integrations (Slack, HubSpot, Salesforce, Google Calendar, …).

No Composio code or research artefact existed before this spike. The
purpose of this ADR is to lock in three decisions before #57 (OAuth
migration) and #58 (7-day soak) start:

1. **Tool shape** — one wrapping tool, or one tool per Composio app?
2. **Token storage** — where do per-user OAuth tokens live, and how are
   they encrypted / refreshed?
3. **Cost envelope** — does the free tier cover the single-user budget
   declared in SPEC §5.6 ("Cost Estimation"), and what is the projected
   spend at the expected daily call volume?

## Considered options

### A. Single `ComposioTool` with action dispatch (`<app>.<verb>`) — **chosen**

```yaml
# skill YAML
- name: send-followup
  tool: composio
  action: gmail.send
  approval_required: true
```

- Mirrors the existing `LinearTool` / `EmailSendTool` / `StripeTool`
  shape: one `BaseTool` subclass, dispatch through the `action` argument.
- 864 apps × ~5 actions each ≈ 4,000+ entry points; one class per
  combination is unmaintainable, blows the import graph, and forces a
  re-register on every new Composio addition.
- The supervisor's `_HIGH_STAKES_ACTIONS` set already accepts dotted
  names (it is checked via membership, not regex), so
  `composio.gmail.send` slots in without changes.
- Phase 1–3 whitelists key off `BaseTool.required_integrations`; we keep
  that field empty and gate per-action authorization inside `execute()`,
  consulting the user's connected `Integration` rows.

### B. One `BaseTool` per Composio app (e.g. `ComposioGmailTool`,
   `ComposioGitHubTool`)

- Pro: reuses the existing `required_integrations` whitelist mechanism
  with zero new logic; per-app rate limits map cleanly onto
  `INTEGRATION_RATE_LIMITS` (SPEC §5.5.2).
- Con: 100+ class files, all near-identical thin wrappers around the
  same Composio SDK; every new Composio integration now needs a PR,
  defeating the point of using Composio in the first place.
- Con: the skill YAML grows from `tool: composio, action: gmail.send` to
  `tool: composio_gmail, action: send` — the dotted form already
  encodes both pieces of information.

### C. Direct SDK use from inside skill YAML (no wrapping tool)

- Rejected: bypasses `BaseTool`, so the rate-limiter, retry policy,
  `validate_auth` contract, and `ToolResult` envelope all stop applying.
  Also breaks the supervisor's high-stakes gate, which is a security
  regression (AGENTS.md Rule 2).

## Decision

**Adopt option A** — a single `ComposioTool` (POC landed in this PR at
`backend/tools/integrations/composio.py`). Production dispatch table,
rate-limit map, and SDK pin land in #57.

## Token storage

- **API key (one per install):** `COMPOSIO_API_KEY` in `.env`. Read at
  startup; never logged (must pass through `scrub()` per AGENTS.md
  Rule 7).
- **Per-user OAuth tokens (Gmail, GitHub, …):** stored on the existing
  `Integration` row in PGLite. The `credentials_encrypted` column is a
  Fernet-encrypted JSON blob (`{access_token, refresh_token, expires_at,
  scope}`) — same envelope used by Phase 1 direct integrations and
  validated by `backend/tests/unit/test_fernet_round_trip.py`
  (SPEC §3b.5).
- **Refresh handling:** Composio refreshes tokens on its side; MindForge
  stores only the Composio "connected_account_id" plus a short-lived
  bearer the SDK returns. On a 401 from Composio we re-fetch the bearer
  rather than touching the upstream provider directly (Composio is the
  source of truth for the OAuth grant). Refresh logic lives in #57.
- **Rotation:** the `FERNET_KEY` rotation procedure already documented
  in SPEC §3b.5 covers Composio blobs unchanged; no new key needed.

## Cost estimate

Inputs (per user-supplied operating profile and SPEC §5.6):

| Input | Value |
|---|---|
| High-stakes actions/day (drafts approved + executed) | ~20 |
| Background reads/day (email scan, calendar poll) | ~80 |
| Total Composio calls/day | ~100 |
| Composio free tier cap | 1,000 calls/month |
| Composio paid tier (Hobby) | $25/mo, 10,000 calls |

| Scenario | Monthly calls | Monthly cost |
|---|---|---|
| Light (drafts only, ~20/day) | ~600 | **$0** (free tier) |
| Moderate (drafts + scans, ~100/day) | ~3,000 | **$25** (Hobby) |
| Heavy (full Phase 4 workload, ~500/day) | ~15,000 | **$25 + overage** (~$50–75) |

The moderate row aligns with SPEC §5.6's $0–$85/month total budget. The
free tier is enough for **drafts-only** evaluation; the $25 Hobby tier
covers the full Phase 4 24/7 monitoring workload. No infra cost is
incurred until #57 enables the SDK call-paths.

## Consequences

### Positive
- One tool surface to maintain regardless of how many Composio apps we
  enable.
- Phase 1–3 integrations (Gmail/GitHub/Linear/Stripe direct) keep
  working — no change to existing code paths until #57.
- Skill YAML stays terse (`tool: composio, action: gmail.send`).
- The Phase 4 cost stays under SPEC's published budget.

### Negative / risks
- The `<app>.<verb>` dispatcher is one method that touches every
  Composio app — a bug there is a blast radius across all integrations.
  Mitigation: per-action unit tests, contract tests against a recorded
  fixture set in #57.
- Composio is a third-party dependency (SPEC §6's "Third-Party API
  Risk" applies). Outage = MindForge Phase 4 features degrade. We keep
  the Phase 1 direct integrations as a fallback for Gmail / GitHub /
  Linear / Stripe.
- Per-user OAuth means the spec's HMAC-on-memory scheme (SPEC §3b.5)
  must still apply to any data Composio returns and we embed — the
  existing `sanitize_for_memory()` defence (AGENTS.md "How to Add an
  Integration" step 6) covers this.

## Out of scope (tracked elsewhere)

| Topic | Tracked in |
|---|---|
| Live SDK pin + dispatcher implementation | #57 |
| OAuth migration for Gmail + Google Calendar | #57 |
| 7-day continuous-run smoke test | #58 |
| Per-action rate-limit table | #57 |
| Skill marketplace (depends on Phase 3 validator) | SPEC §5.4 |

## Verification of the spike POC

- `backend/tools/integrations/composio.py` imports cleanly with the
  Composio SDK absent (Phase 1–3 unaffected).
- `backend/tests/unit/test_composio_tool.py` — 7 tests, all green.
- `register_all_tools()` is unchanged; ToolRegistry does not contain
  `"composio"` after startup.
- `ENABLE_COMPOSIO=false` (the default) → `execute()` returns
  `COMPOSIO_DISABLED_ERROR` without making a network call.
