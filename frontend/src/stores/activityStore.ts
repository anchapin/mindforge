/**
 * System Activity Store (#92).
 *
 * Tracks proactive system events: billing anomalies, calendar conflicts,
 * follow-up drafts created, and Temporal worker status changes.
 *
 * These differ from Notifications (user-facing alerts from WSMessageHandler)
 * in that they represent background monitoring events, not task state changes.
 * The SystemActivity section in TaskTracker shows the last 24h of these.
 *
 * WS message types (per SPEC.md Section 2.5 proactive events):
 *   billing_anomaly_detected
 *   calendar_conflict_detected
 *   follow_up_draft_created
 *   worker_status_changed
 */

import { create } from "zustand";

export type ActivityCategory =
  | "billing"
  | "calendar"
  | "follow_up"
  | "worker";

export interface SystemActivity {
  id: string;
  category: ActivityCategory;
  /** Human-readable one-line summary */
  summary: string;
  /** Optional detailed description (shown on expand) */
  detail?: string;
  /** CTA label — e.g. "View" or "Resolve" */
  actionLabel?: string;
  /** Navigation target when action is clicked */
  actionTarget?: string;
  /** "critical" | "warning" | "info" */
  severity: "critical" | "warning" | "info";
  timestamp: string;
  /** Whether the user has dismissed this */
  dismissed: boolean;
}

interface SystemActivityState {
  activities: SystemActivity[];
  /** Push a new activity; de-dup by id */
  pushActivity: (activity: SystemActivity) => void;
  /** Dismiss an activity (hides it from the list) */
  dismissActivity: (id: string) => void;
  /** Clear all dismissed activities */
  clearAll: () => void;
}

export const useSystemActivityStore = create<SystemActivityState>((set) => ({
  activities: [],

  pushActivity: (activity) =>
    set((state) => {
      // De-dup
      const exists = state.activities.some((a) => a.id === activity.id);
      if (exists) return state;
      return {
        activities: [activity, ...state.activities].slice(0, 50),
      };
    }),

  dismissActivity: (id) =>
    set((state) => ({
      activities: state.activities.map((a) =>
        a.id === id ? { ...a, dismissed: true } : a,
      ),
    })),

  clearAll: () => set({ activities: [] }),
}));