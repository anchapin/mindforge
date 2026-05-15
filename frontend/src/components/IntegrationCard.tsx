/**
 * IntegrationCard.tsx — card for a single integration (#93)
 */

import type { Integration } from "../lib/api";

const STATUS_CONFIG: Record<
  string,
  { label: string; className: string }
> = {
  active: { label: "Active", className: "bg-green-900/40 text-green-400 border border-green-800" },
  revoked: { label: "Revoked", className: "bg-yellow-900/40 text-yellow-400 border border-yellow-800" },
  error: { label: "Error", className: "bg-red-900/40 text-red-400 border border-red-800" },
  expired: { label: "Expired", className: "bg-orange-900/40 text-orange-400 border border-orange-800" },
};

const APP_ICONS: Record<string, string> = {
  github: "💻",
  stripe: "💳",
  gmail: "📧",
  linear: "📊",
  slack: "💬",
};

const AGENT_LABELS: Record<string, string> = {
  coo: "COO",
  cmo: "CMO",
  researcher: "Researcher",
  engineer: "Engineer",
};

interface IntegrationCardProps {
  integration: Integration;
  onTest: () => void;
  onSettings: () => void;
  onDisconnect: () => void;
  testResult?: { success: boolean; message: string };
  isTesting: boolean;
}

export function IntegrationCard({
  integration,
  onTest,
  onSettings,
  onDisconnect,
  testResult,
  isTesting,
}: IntegrationCardProps) {
  const statusCfg =
    STATUS_CONFIG[integration.status] ?? {
      label: integration.status,
      className: "bg-zinc-700 text-zinc-400",
    };

  const icon = APP_ICONS[integration.app_name] ?? "🔌";

  const lastSync = integration.last_sync_at
    ? formatRelativeTime(new Date(integration.last_sync_at))
    : "Never";

  return (
    <div className="rounded-lg border border-zinc-700 bg-zinc-800 p-4 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <span className="text-xl" aria-hidden="true">{icon}</span>
          <div>
            <p className="font-medium capitalize">{integration.app_name}</p>
            <span className={`mt-1 inline-block rounded px-1.5 py-0.5 text-xs font-medium ${statusCfg.className}`}>
              {statusCfg.label}
            </span>
          </div>
        </div>
      </div>

      {/* Permissions + agents summary */}
      <div className="text-xs text-zinc-500 space-y-1">
        {integration.permissions?.length > 0 ? (
          <p>Permissions: {integration.permissions.join(", ")}</p>
        ) : null}
        {integration.allowed_agents?.length > 0 ? (
          <p>
            Agents:{" "}
            {integration.allowed_agents
              .map((a) => AGENT_LABELS[a] ?? a)
              .join(", ")}
          </p>
        ) : (
          <p>No agent restrictions</p>
        )}
        <p>Last sync: {lastSync}</p>
      </div>

      {/* Test result */}
      {testResult && (
        <div
          className={`rounded px-3 py-2 text-xs ${
            testResult.success
              ? "bg-green-900/30 text-green-400"
              : "bg-red-900/30 text-red-400"
          }`}
          role="status"
        >
          {testResult.message}
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1 border-t border-zinc-700">
        <button
          onClick={onTest}
          disabled={isTesting}
          className="flex-1 rounded bg-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-600 disabled:opacity-50"
        >
          {isTesting ? "Testing..." : "Test"}
        </button>
        <button
          onClick={onSettings}
          className="flex-1 rounded bg-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-200 hover:bg-zinc-600"
        >
          Settings
        </button>
        <button
          onClick={onDisconnect}
          className="flex-1 rounded bg-red-900/40 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-900/60 border border-red-800"
        >
          Disconnect
        </button>
      </div>
    </div>
  );
}

function formatRelativeTime(date: Date): string {
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}