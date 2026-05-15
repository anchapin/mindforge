## Use Case
User wants to configure when and how the system monitors their inbox, follows up on emails, and alerts them about billing anomalies — without editing .env files.

## Proposed Solution
Implement the Settings UI section described in SPEC.md Section 2.7.4 (Proactive Monitoring).

**Backend already exists:**
- UserPreference table has all fields: proactive_monitoring_enabled, email_check_interval_minutes, calendar_check_interval_minutes, billing_alert_threshold_usd
- GET/PUT /api/preferences endpoints exist

**What needs building:**
- Frontend SettingsPage component with proactive monitoring section
- Toggle switches for each monitoring type
- Dropdowns for intervals and thresholds
- PUT /api/preferences call on save
- Mount at /settings route in TanStack Router

**Components needed:**
- SettingsPage.tsx with ProactiveSettings section
- Toggle component (or use FluxUI toggle)
- Select component for dropdown intervals

## Phase Alignment
- [ ] Phase 3 — Proactive Execution

## References
- SPEC.md Section 2.7.4
- SPEC.md Section 2.5 (Dashboard features: "Integration manager — connect/disconnect apps")