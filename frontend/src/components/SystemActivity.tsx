/**
 * SystemActivity component (#92).
 *
 * Displays proactive events from the activity store:
 * - billing_anomaly_detected
 * - calendar_conflict_detected
 * - follow_up_draft_created
 * - worker_status_changed
 *
 * Per SPEC.md Section 2.7.4, shows the last 24h of system activity with
 * "View/Dismiss" actions for each entry.
 *
 * Styled to match the TaskTracker section layout:
 *   ┌─ SYSTEM ACTIVITY (last 24h) ────────────────────────┐
 *   │  📨 3 follow-up drafts created (all approved)        │
 *   │  ⚠️ Billing anomaly detected: Stripe renewal $149   │
 *   │     [View →] [Dismiss]                              │
 *   │  📅 Calendar conflict: Team sync 2pm overlaps...    │
 *   │     [Resolve →]                                     │
 *   │  🔴 Temporal worker restarted at 03:12 (recovered)  │
 */

import {
  useSystemActivityStore,
  type ActivityCategory,
} from "../stores/activityStore";
import { Activity, AlertTriangle, Calendar, Cpu, Mail } from "lucide-react";
import { useNavigate } from "@tanstack/react-router";

const ICON_MAP = {
  billing: AlertTriangle,
  calendar: Calendar,
  follow_up: Mail,
  worker: Cpu,
} as const;

const SEVERITY_COLOR_MAP = {
  critical: "text-red-400",
  warning: "text-amber-400",
  info: "text-blue-400",
} as const;

const SEVERITY_BG_MAP = {
  critical: "bg-red-900/20 border-red-800",
  warning: "bg-amber-900/20 border-amber-800",
  info: "bg-blue-900/20 border-blue-800",
} as const;

function timeAgo(timestamp: string): string {
  const seconds = Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

interface ActivityItemProps {
  activity: ReturnType<typeof useSystemActivityStore.getState>["activities"][number];
  onDismiss: (id: string) => void;
}

function ActivityItem({ activity, onDismiss }: ActivityItemProps) {
  const Icon = ICON_MAP[activity.category];
  const colorClass = SEVERITY_COLOR_MAP[activity.severity];
  const bgClass = SEVERITY_BG_MAP[activity.severity];
  const navigate = useNavigate();

  const handleView = () => {
    if (activity.actionTarget) {
      navigate({ to: activity.actionTarget });
    }
  };

  return (
    <div className={`flex items-start gap-3 rounded-md border p-3 ${bgClass}`}>
      <Icon size={18} className={`mt-0.5 shrink-0 ${colorClass}`} />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-zinc-200">{activity.summary}</p>
        {activity.detail && (
          <p className="mt-1 text-xs text-zinc-400">{activity.detail}</p>
        )}
        <p className="mt-1 text-xs text-zinc-500">{timeAgo(activity.timestamp)}</p>
      </div>
      <div className="flex shrink-0 gap-1">
        {activity.actionLabel && activity.actionTarget && (
          <button
            onClick={handleView}
            className="rounded px-2 py-1 text-xs text-indigo-400 hover:bg-zinc-700"
          >
            {activity.actionLabel} →
          </button>
        )}
        <button
          onClick={() => onDismiss(activity.id)}
          className="rounded px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-700 hover:text-zinc-300"
        >
          Dismiss
        </button>
      </div>
    </div>
  );
}

export function SystemActivity() {
  const { activities, dismissActivity } = useSystemActivityStore();

  // Show only non-dismissed, last-24h activities
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const visible = activities.filter(
    (a) => !a.dismissed && new Date(a.timestamp).getTime() > cutoff,
  );

  // Group by category for summary count
  const byCategory = visible.reduce<
    Partial<Record<ActivityCategory, number>>
  >((acc, a) => {
    acc[a.category] = (acc[a.category] ?? 0) + 1;
    return acc;
  }, {});

  if (visible.length === 0) {
    return (
      <section>
        <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-400 uppercase tracking-wide">
          <Activity size={14} />
          System Activity
        </h2>
        <p className="text-sm text-zinc-500">No system activity in the last 24 hours.</p>
      </section>
    );
  }

  return (
    <section>
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold text-zinc-400 uppercase tracking-wide">
        <Activity size={14} />
        System Activity
        <span className="text-xs font-normal text-zinc-600 normal-case">(last 24h)</span>
      </h2>

      {/* Summary line */}
      <div className="mb-3 text-xs text-zinc-500">
        {byCategory.billing && (
          <span className="inline-flex items-center gap-1">
            <AlertTriangle size={12} className="text-amber-400" />
            {byCategory.billing} billing {byCategory.billing === 1 ? "alert" : "alerts"}
            {", "}
          </span>
        )}
        {byCategory.calendar && (
          <span className="inline-flex items-center gap-1">
            <Calendar size={12} className="text-amber-400" />
            {byCategory.calendar} calendar {byCategory.calendar === 1 ? "conflict" : "conflicts"}
            {", "}
          </span>
        )}
        {byCategory.follow_up && (
          <span className="inline-flex items-center gap-1">
            <Mail size={12} className="text-blue-400" />
            {byCategory.follow_up} follow-up {byCategory.follow_up === 1 ? "draft" : "drafts"}
            {", "}
          </span>
        )}
        {byCategory.worker && (
          <span className="inline-flex items-center gap-1">
            <Cpu size={12} className="text-zinc-400" />
            {byCategory.worker} worker {byCategory.worker === 1 ? "event" : "events"}
          </span>
        )}
      </div>

      <div className="space-y-2">
        {visible.map((activity) => (
          <ActivityItem
            key={activity.id}
            activity={activity}
            onDismiss={dismissActivity}
          />
        ))}
      </div>

      {activities.length > visible.length && (
        <button className="mt-3 text-xs text-indigo-400 hover:text-indigo-300">
          View full activity log →
        </button>
      )}
    </section>
  );
}