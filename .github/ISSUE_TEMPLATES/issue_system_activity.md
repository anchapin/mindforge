## Use Case
The dashboard shows task status, but users need a unified view of proactive events — follow-up drafts created, billing anomalies detected, calendar conflicts, and Temporal worker status — all in one place.

## Proposed Solution
Implement the System Activity section per SPEC.md Section 2.7.4.

**What needs building:**
- SystemActivity component in frontend/src/components/
- Activity log entries: email follow-ups, billing alerts, calendar conflicts, worker status
- WS message handling for proactive events (billing_alert, calendar_conflict, follow_up_created, worker_status)
- "Dismiss" action for alerts
- "View" action to navigate to relevant context
- Integration with NotificationBell for alert count

**Backend requirements:**
- WS messages for proactive events need to be defined:
  - billing_anomaly_detected
  - calendar_conflict_detected
  - follow_up_draft_created
  - worker_status_changed

## Phase Alignment
- [ ] Phase 3 — Proactive Execution

## References
- SPEC.md Section 2.7.4 (System Activity section)
- SPEC.md Section 2.5 (WS message protocol — proactive events)
- SPEC.md Section 2.6 (Proactive Execution capabilities)