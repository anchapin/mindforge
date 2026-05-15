/**
 * IntegrationManager.tsx — Integration list page (#93)
 *
 * Features:
 *  1. Integration list — cards for each connected app
 *  2. Status indicators — active/revoked/error/expired badges
 *  3. Test connection — POST /api/integrations/{id}/test
 *  4. Permissions scope — show/edit what agents can do
 *  5. Allowed agents — which agents can use this integration
 *  6. Disconnect — remove integration with confirmation
 *  7. OAuth flow — "Connect" button that initiates OAuth
 *  8. Last sync — timestamp of last successful sync
 */

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  listIntegrations,
  createIntegration,
  deleteIntegration,
  testIntegration,
  updateIntegration,
  type Integration,
} from "../lib/api";
import { IntegrationCard } from "../components/IntegrationCard";
import { ConnectIntegrationModal } from "../components/ConnectIntegrationModal";
import { IntegrationSettingsModal } from "../components/IntegrationSettingsModal";

// Supported apps that can be connected via OAuth or token
export const SUPPORTED_APPS = [
  { app_name: "github", label: "GitHub", icon: "💻", color: "bg-zinc-700" },
  { app_name: "stripe", label: "Stripe", icon: "💳", color: "bg-violet-700" },
  { app_name: "gmail", label: "Gmail", icon: "📧", color: "bg-red-700" },
  { app_name: "linear", label: "Linear", icon: "📊", color: "bg-indigo-700" },
  { app_name: "slack", label: "Slack", icon: "💬", color: "bg-pink-700" },
] as const;

export type SupportedApp = (typeof SUPPORTED_APPS)[number]["app_name"];

export default function IntegrationsPage() {
  const queryClient = useQueryClient();

  const { data: integrations = [], isLoading } = useQuery({
    queryKey: ["integrations"],
    queryFn: listIntegrations,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteIntegration,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });

  const testMutation = useMutation({
    mutationFn: ({ id }: { id: string }) => testIntegration(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });

  const updateMutation = useMutation({
    mutationFn: (payload: {
      id: string;
      permissions: string[];
      allowed_agents: string[];
    }) => updateIntegration(payload.id, payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });

  // Modal state
  const [connectApp, setConnectApp] = useState<Integration | null>(null);
  const [settingsApp, setSettingsApp] = useState<Integration | null>(null);
  const [disconnectApp, setDisconnectApp] = useState<Integration | null>(null);
  const [testResult, setTestResult] = useState<{
    id: string;
    success: boolean;
    message: string;
  } | null>(null);

  const handleConnect = async (appName: string, token: string) => {
    await createIntegration({ app_name: appName, token });
    queryClient.invalidateQueries({ queryKey: ["integrations"] });
    setConnectApp(null);
  };

  const handleDisconnect = async () => {
    if (!disconnectApp) return;
    await deleteMutation.mutateAsync(disconnectApp.id);
    setDisconnectApp(null);
  };

  const handleTest = async (id: string) => {
    const result = await testMutation.mutateAsync({ id });
    setTestResult({ id, success: result.success, message: result.message });
  };

  const handleSettingsSave = async (permissions: string[], allowed_agents: string[]) => {
    if (!settingsApp) return;
    await updateMutation.mutateAsync({
      id: settingsApp.id,
      permissions,
      allowed_agents,
    });
    setSettingsApp(null);
  };

  // Which apps are already connected?
  const connectedAppNames = new Set(integrations.map((i) => i.app_name));
  const availableToConnect = SUPPORTED_APPS.filter(
    (a) => !connectedAppNames.has(a.app_name)
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Integrations</h1>
          <p className="mt-1 text-sm text-zinc-400">
            Connect apps to enable your AI team to work on your behalf.
          </p>
        </div>
      </div>

      {/* Connected integrations */}
      <section aria-labelledby="connected-heading">
        <h2 id="connected-heading" className="mb-3 text-sm font-semibold uppercase tracking-wider text-zinc-500">
          Connected
        </h2>

        {isLoading ? (
          <p className="text-sm text-zinc-400">Loading...</p>
        ) : integrations.length === 0 ? (
          <p className="rounded border border-dashed border-zinc-700 p-6 text-center text-sm text-zinc-500">
            No integrations connected yet. Connect your first app below.
          </p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {integrations.map((integration) => (
              <IntegrationCard
                key={integration.id}
                integration={integration}
                onTest={() => handleTest(integration.id)}
                onSettings={() => setSettingsApp(integration)}
                onDisconnect={() => setDisconnectApp(integration)}
                testResult={
                  testResult?.id === integration.id
                    ? testResult
                    : undefined
                }
                isTesting={testMutation.isPending && testMutation.variables?.id === integration.id}
              />
            ))}
          </div>
        )}
      </section>

      {/* Available to connect */}
      <section aria-labelledby="available-heading">
        <h2 id="available-heading" className="mb-3 text-sm font-semibold uppercase tracking-wider text-zinc-500">
          Available
        </h2>
        {availableToConnect.length === 0 ? (
          <p className="text-sm text-zinc-500">All supported apps are connected.</p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {availableToConnect.map((app) => (
              <button
                key={app.app_name}
                onClick={() =>
                  setConnectApp({
                    id: "",
                    app_name: app.app_name,
                    status: "active",
                    permissions: [],
                    allowed_agents: [],
                    created_at: "",
                    updated_at: "",
                  } as Integration)
                }
                className="flex items-center gap-3 rounded border border-dashed border-zinc-600 bg-zinc-800/30 p-4 text-left transition hover:border-zinc-500 hover:bg-zinc-800/60"
              >
                <span className="text-2xl">{app.icon}</span>
                <div>
                  <p className="font-medium text-zinc-200">{app.label}</p>
                  <p className="text-xs text-zinc-500">Connect via token</p>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      {/* OAuth note */}
      <p className="text-xs text-zinc-600">
        OAuth flows for Gmail, GitHub, and other OAuth-enabled apps are available
        in Phase 4. Currently, use token-based authentication.
      </p>

      {/* Connect modal */}
      {connectApp && (
        <ConnectIntegrationModal
          integration={connectApp}
          onConnect={handleConnect}
          onClose={() => setConnectApp(null)}
        />
      )}

      {/* Settings modal */}
      {settingsApp && (
        <IntegrationSettingsModal
          integration={settingsApp}
          onSave={handleSettingsSave}
          onClose={() => setSettingsApp(null)}
          isSaving={updateMutation.isPending}
        />
      )}

      {/* Disconnect confirmation */}
      {disconnectApp && (
        <DisconnectConfirmation
          appName={disconnectApp.app_name}
          onConfirm={handleDisconnect}
          onCancel={() => setDisconnectApp(null)}
          isLoading={deleteMutation.isPending}
        />
      )}
    </div>
  );
}

function DisconnectConfirmation({
  appName,
  onConfirm,
  onCancel,
  isLoading,
}: {
  appName: string;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="disconnect-title"
        className="w-full max-w-sm rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl"
      >
        <h3 id="disconnect-title" className="text-lg font-semibold">
          Disconnect {appName}?
        </h3>
        <p className="mt-2 text-sm text-zinc-400">
          This will remove the integration and revoke agent access. You can
          reconnect later.
        </p>
        <div className="mt-4 flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="rounded px-4 py-2 text-sm text-zinc-400 hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isLoading}
            className="rounded bg-red-700 px-4 py-2 text-sm text-white hover:bg-red-600 disabled:opacity-50"
          >
            {isLoading ? "Removing..." : "Remove Integration"}
          </button>
        </div>
      </div>
    </div>
  );
}