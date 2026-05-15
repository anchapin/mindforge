/**
 * IntegrationSettingsModal.tsx — permissions + allowed agents settings (#93)
 */

import { useState } from "react";
import type { Integration } from "../lib/api";

interface IntegrationSettingsModalProps {
  integration: Integration;
  onSave: (permissions: string[], allowed_agents: string[]) => Promise<void>;
  onClose: () => void;
  isSaving: boolean;
}

const AGENT_OPTIONS = [
  { value: "coo", label: "COO — Planner/Overseer" },
  { value: "cmo", label: "CMO — Marketing/Content" },
  { value: "researcher", label: "Researcher — Data/Web" },
  { value: "engineer", label: "Engineer — Code/GitHub" },
];

const PERMISSION_OPTIONS = [
  { value: "read", label: "Read — view data, pull information" },
  { value: "write", label: "Write — create, update, send on your behalf" },
];

export function IntegrationSettingsModal({
  integration,
  onSave,
  onClose,
  isSaving,
}: IntegrationSettingsModalProps) {
  const [permissions, setPermissions] = useState<string[]>(
    integration.permissions ?? [],
  );
  const [allowedAgents, setAllowedAgents] = useState<string[]>(
    integration.allowed_agents ?? [],
  );

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await onSave(permissions, allowedAgents);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        className="w-full max-w-md rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 id="settings-title" className="text-lg font-semibold capitalize">
            {integration.app_name} Settings
          </h3>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <svg
              className="h-5 w-5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-6">
          {/* Permissions */}
          <fieldset>
            <legend className="mb-2 text-sm font-medium text-zinc-300">
              Permissions
            </legend>
            <p className="mb-2 text-xs text-zinc-500">
              Controls what agents can do with this integration. At least one
              permission is required for any agent access.
            </p>
            <div className="space-y-2">
              {PERMISSION_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className="flex items-start gap-2 rounded border border-zinc-700 bg-zinc-800 p-3 cursor-pointer hover:bg-zinc-750"
                >
                  <input
                    type="checkbox"
                    checked={permissions.includes(opt.value)}
                    onChange={(e) => {
                      setPermissions((prev) =>
                        e.target.checked
                          ? [...prev, opt.value]
                          : prev.filter((p) => p !== opt.value),
                      );
                    }}
                    className="mt-0.5 h-4 w-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-900"
                  />
                  <div>
                    <p className="text-sm font-medium text-zinc-200">
                      {opt.label}
                    </p>
                  </div>
                </label>
              ))}
            </div>
          </fieldset>

          {/* Allowed agents */}
          <fieldset>
            <legend className="mb-2 text-sm font-medium text-zinc-300">
              Allowed Agents
            </legend>
            <p className="mb-2 text-xs text-zinc-500">
              Only these agents can use this integration. Leave all unchecked
              to block all agents (you can enable specific agents later).
            </p>
            <div className="space-y-2">
              {AGENT_OPTIONS.map((opt) => (
                <label
                  key={opt.value}
                  className="flex items-start gap-2 rounded border border-zinc-700 bg-zinc-800 p-3 cursor-pointer hover:bg-zinc-700/50"
                >
                  <input
                    type="checkbox"
                    checked={allowedAgents.includes(opt.value)}
                    onChange={(e) => {
                      setAllowedAgents((prev) =>
                        e.target.checked
                          ? [...prev, opt.value]
                          : prev.filter((a) => a !== opt.value),
                      );
                    }}
                    className="mt-0.5 h-4 w-4 rounded border-zinc-600 bg-zinc-700 text-blue-500 focus:ring-blue-500 focus:ring-offset-zinc-900"
                  />
                  <div>
                    <p className="text-sm font-medium text-zinc-200">
                      {opt.label}
                    </p>
                  </div>
                </label>
              ))}
            </div>
          </fieldset>

          {/* Actions */}
          <div className="flex justify-end gap-3 border-t border-zinc-700 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded px-4 py-2 text-sm text-zinc-400 hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSaving}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {isSaving ? "Saving..." : "Save Settings"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}