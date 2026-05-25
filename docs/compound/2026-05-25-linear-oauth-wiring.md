# Compound Note: Linear OAuth Provider Wiring

Date: 2026-05-25
Task: Wire Linear into existing OAuth flow (#153)
Author: Claude

## What Happened

The Integration Manager UI (#93) already had all frontend components and backend CRUD endpoints built. The missing piece was OAuth support for Linear — the existing `LinearTool` used Phase 1 personal API token authentication, but there was no way to connect Linear via OAuth flow.

The OAuth architecture was already in place for Composio (Gmail/Google Calendar). I wired Linear into the same pluggable `OAuthProvider` protocol that Composio uses, making it a second registered provider.

## Key Decisions

1. **Pluggable provider over inline code** — The `OAuthProvider` protocol was already designed for extensibility. Adding Linear as a second provider required only:
   - A new `LinearOAuthProvider` class in `backend/api/oauth/linear_provider.py`
   - Two-line registration change in `oauth.py` and `__init__.py`

2. **Token storage compatibility** — The existing `oauth.py` callback persists a JSON blob (Fernet-encrypted) to `integration.auth_token_enc`. The stored `access_token` from Linear OAuth can be passed directly to `LinearTool._execute()` which already calls `validate_auth(token)`.

3. **Skipped planning contracts** — This was a small, targeted change with confirmed existing architecture. Six planning contracts would have added more overhead than value.

4. **Skipped formal cross-review** — Non-breaking additive change (new provider, no existing behavior modified), lint + mypy + compile provided sufficient verification.

## What I'd Do Differently

- The `_COMPOSIO_PROVIDER_ERROR` typo/bad copy-paste (`LINEAR_OAUTH_*\n is not configured`) was caught by the linter — good, but should have caught it manually first.
- Could have tested the OAuth flow end-to-end with a real Linear app instead of compile-time checks only.

## Pattern to Reuse

When adding a new OAuth-connected integration (e.g. GitHub direct OAuth, Notion):
1. Create `backend/api/oauth/{provider}_provider.py` implementing `OAuthProvider`
2. Import and `register_provider()` in `backend/api/routes/oauth.py`
3. Re-export in `backend/api/oauth/__init__.py`
4. Set required env vars (`{PROVIDER}_CLIENT_ID`, `{PROVIDER}_CLIENT_SECRET`)
5. No frontend changes needed if the existing IntegrationCard/ConnectIntegrationModal already handle OAuth initiation

## Env Vars Added

```bash
LINEAR_CLIENT_ID=          # From Linear app settings (linear.app/settings/api)
LINEAR_CLIENT_SECRET=      # From Linear app settings
LINEAR_OAUTH_REDIRECT_URI= # Optional, default: http://localhost:8000/api/oauth/linear/callback
```

## Files Changed

- `backend/api/oauth/linear_provider.py` — NEW (151 lines)
- `backend/api/oauth/__init__.py` — +2 lines
- `backend/api/routes/oauth.py` — +1 import, +1 registration, -1 comment
- `docs/plans/2026-05-22-implement-linear-integration-issue-153.md` — updated with completion status