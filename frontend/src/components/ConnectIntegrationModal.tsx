/**
 * ConnectIntegrationModal.tsx — token-based connection modal (#93)
 */

import { useState } from "react";
import type { Integration } from "../lib/api";

interface ConnectIntegrationModalProps {
  integration: Integration;
  onConnect: (appName: string, token: string) => Promise<void>;
  onClose: () => void;
}

const APP_LABELS: Record<string, string> = {
  github: "GitHub",
  stripe: "Stripe",
  gmail: "Gmail",
  linear: "Linear",
  slack: "Slack",
};

const TOKEN_PLACEHOLDERS: Record<string, string> = {
  github: "ghp_xxxxxxxxxxxxxxxxxxxx",
  stripe: "sk_live_xxxxxxxxxxxxxxxxxxxx",
  gmail: "ya29.xxxxxxxxxxxxxxxxxxxxxx",
  linear: "lin_api_xxxxxxxxxxxxxxxxxxxx",
  slack: "xoxb-xxxxxxxxxxxxxxxxxxxx",
};

export function ConnectIntegrationModal({
  integration,
  onConnect,
  onClose,
}: ConnectIntegrationModalProps) {
  const [token, setToken] = useState("");
  const [isConnecting, setIsConnecting] = useState(false);

  const label = APP_LABELS[integration.app_name] ?? integration.app_name;
  const placeholder = TOKEN_PLACEHOLDERS[integration.app_name] ?? "Paste your token here";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token.trim()) return;
    setIsConnecting(true);
    try {
      await onConnect(integration.app_name, token.trim());
    } finally {
      setIsConnecting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="connect-title"
        className="w-full max-w-md rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 id="connect-title" className="text-lg font-semibold">
            Connect {label}
          </h3>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <p className="mb-4 text-sm text-zinc-400">
          Enter your API token or access token for <strong>{label}</strong>.
          Tokens are encrypted at rest using Fernet (AES-256).
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="token-input" className="block text-sm font-medium text-zinc-300 mb-1">
              Access Token
            </label>
            <input
              id="token-input"
              type="password"
              value={token}
              onChange={(e) => setToken(e.target.value)}
              placeholder={placeholder}
              required
              autoFocus
              className="w-full rounded border border-zinc-600 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 placeholder-zinc-500 focus:border-zinc-400 focus:outline-none focus:ring-1 focus:ring-zinc-500"
            />
          </div>

          <div className="flex justify-end gap-3">
            <button
              type="button"
              onClick={onClose}
              className="rounded px-4 py-2 text-sm text-zinc-400 hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!token.trim() || isConnecting}
              className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-500 disabled:opacity-50"
            >
              {isConnecting ? "Connecting..." : "Connect"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}