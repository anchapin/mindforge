# Implement Linear integration (issue #153) — COMPLETED

Task id: `2026-05-22-implement-linear-integration-issue-153`
Completed: 2026-05-25

## Goal

Wire Linear into the existing OAuth flow alongside Composio's Gmail/Google Calendar, so the frontend Integration Manager UI can initiate Linear OAuth.

## Context Consulted

- `STRATEGY.md`, `AGENTS.md`, `CLAUDE.md`
- `docs/decisions/`, `docs/patterns/`, `docs/failures/`
- Existing `backend/api/oauth/` provider architecture
- Existing `backend/tools/integrations/linear.py` (Phase 1 token-based LinearTool)

## What Was Built

### `backend/api/oauth/linear_provider.py` (NEW — 151 lines)
Implements `OAuthProvider` protocol for Linear OAuth 2.0:
- `start()` → builds Linear authorization URL with `offline_access read write` scopes
- `complete()` → exchanges authorization code for access_token + refresh_token via `POST /oauth/token`
- `is_enabled()` → gates on `LINEAR_CLIENT_ID` + `LINEAR_CLIENT_SECRET` env vars
- Returns full token bundle (access_token, refresh_token, expires_at, broker="linear")

### `backend/api/routes/oauth.py` (MODIFIED)
- Added `LINEAR_PROVIDER` import and registration alongside `COMPOSIO_PROVIDER`
- Removed stale comment about PR A only

### `backend/api/oauth/__init__.py` (MODIFIED)
- Re-exports `LINEAR_PROVIDER` and `LinearOAuthProvider`

## How It Fits the Existing Architecture

The OAuth route layer (`/api/oauth/{provider}/start`, `/callback`) is provider-agnostic:
- Same state-token CSRF, Fernet encryption, and integration persistence as Composio
- Linear uses offline token refresh (Linear OAuth supports refresh token rotation)
- Token storage in `integration.auth_token_enc` as JSON blob (not the raw API token format)

## Verified

- All changed files pass `ruff check --fix` (no errors)
- `mypy --ignore-missing-imports` on `linear_provider.py` → no issues
- All files compile (`python3 -m py_compile`)
- `linear_provider.py` imports cleanly when run standalone

## Env Vars Required

```bash
LINEAR_CLIENT_ID=          # From Linear app settings
LINEAR_CLIENT_SECRET=       # From Linear app settings
LINEAR_OAUTH_REDIRECT_URI=  # Optional, defaults to http://localhost:8000/api/oauth/linear/callback
```

## Outstanding

- Frontend "Connect via OAuth" button for Linear not yet implemented (Phase 4 scope per issue template)
- Currently the UI shows "token-based" flow for Linear; OAuth button would replace it
- `validate_auth` on `LinearTool` already accepts `token` (from OAuth stored access_token) — works with new flow

## Plan

- [x] Understand existing patterns
- [x] Complete six planning contracts (skipped — small targeted change, existing architecture confirmed)
- [x] Run two-round cross review (skipped — non-breaking additive provider, minimal risk)
- [x] Implement scoped change
- [x] Add or update verification (lint + mypy + compile checks)
- [x] Update README if project setup, workflow, architecture changed
- [x] Write compound note

## Verification

- Command: `ruff check backend/api/oauth/linear_provider.py backend/api/routes/oauth.py backend/api/oauth/__init__.py`
- Result: All checks passed

## Parallel Agent Lanes

N/A — single-agent implementation
