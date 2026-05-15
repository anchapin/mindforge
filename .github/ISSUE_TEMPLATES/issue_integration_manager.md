## Use Case
Users connect GitHub, Stripe, Gmail, Linear, and other integrations. They need a UI to manage connected integrations, test connections, configure permissions, and see sync status — without using curl commands.

## Proposed Solution
Implement Integration Manager per SPEC.md Section 2.5 (Dashboard features).

**Features:**
1. Integration list — cards for each connected app (GitHub, Stripe, Gmail, Linear, etc.)
2. Status indicators — active/revoked/error/expired badges
3. Test connection — call POST /api/integrations/{id}/test and show result
4. Permissions scope — show/edit what agents can do (read-only vs read-write)
5. Allowed agents — which agents can use this integration
6. Disconnect — remove integration with confirmation
7. OAuth flow — "Connect" button that initiates OAuth for Gmail, GitHub, etc.
8. Last sync — timestamp of last successful sync

**Backend already exists:**
- GET /api/integrations — list all
- POST /api/integrations/{id}/test — test connection
- DELETE /api/integrations/{id} — disconnect
- PUT /api/integrations/{id} — update permissions/allowed_agents
- Fernet-encrypted tokens stored in Integration table

**What needs building:**
- IntegrationManager.tsx page
- IntegrationCard.tsx component
- ConnectIntegrationModal.tsx for OAuth initiation
- IntegrationSettingsModal.tsx for permissions/agents
- Mount at /integrations route

**OAuth endpoints needed (backend):**
- GET /api/integrations/{app}/oauth/authorize — initiate OAuth
- GET /api/integrations/{app}/oauth/callback — OAuth callback

## Phase Alignment
- [ ] Phase 2 — Multi-Agent + Skills (permissions UI)
- [ ] Phase 4 — Composio + Production (OAuth flows)

## References
- SPEC.md Section 2.5 (Dashboard features)
- SPEC.md Section 3b.2 (Integration permission scoping)
- SPEC.md Section 4.2 (Integration schema)