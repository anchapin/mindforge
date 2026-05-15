/**
 * Integration tests for RootLayout. Combines:
 *   - Notification-bell + clarification-modal wiring (#47)
 *   - Onboarding-gate first-run logic (#46)
 *
 * Notes:
 *  - Mocks the websocket lib so no real connection is attempted.
 *  - Uses memory-history router so we can mount RootLayout in isolation.
 *  - The notification store is reset between tests to avoid cross-test bleed.
 *  - The onboarding gate is suppressed in notification/clarification tests
 *    by returning a non-empty preferences id (post-onboarding state).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";
import { Suspense } from "react";

import { RootLayout } from "./RootLayout";
import { useNotificationStore } from "../../stores/notificationStore";

// Module-level state for the mocked preferences fetch (#46). Tests that
// want first-run behavior set this to { id: "" } in their `beforeEach`.
// Tests that want to suppress the onboarding modal leave it at the default.
let nextPreferencesResponse: { id: string } = { id: "post-onboarding-uuid" };

vi.mock("../../lib/api", () => ({
  // #47 — clarification submitter
  submitClarification: vi.fn().mockResolvedValue(undefined),
  // #46 — first-run gate signal
  fetchPreferences: vi.fn(async () => ({
    id: nextPreferencesResponse.id,
    proactive_monitoring_enabled: true,
    email_check_interval_minutes: 30,
    calendar_check_interval_minutes: 60,
    billing_alert_threshold_usd: 50,
    notification_channel: "dashboard",
    notification_handle: null,
    created_at: "2026-05-15T00:00:00Z",
    updated_at: "2026-05-15T00:00:00Z",
  })),
}));

// Avoid the real WS singleton trying to connect (WSMessageHandler subscribes)
vi.mock("../../lib/websocket", () => ({
  getGlobalWS: () => ({ subscribe: () => () => {} }),
}));

// Both call patterns must be supported:
//   useTaskStore((s) => s.wsDisconnected)        -> RootLayout
//   useTaskStore()                                -> WSMessageHandler destructure
vi.mock("../../stores/taskStore", () => {
  const fakeState = {
    wsDisconnected: false,
    upsertTask: () => {},
    setWsDisconnected: () => {},
    updateTaskStatus: () => {},
  };
  const useTaskStore: any = (selector?: any) =>
    typeof selector === "function" ? selector(fakeState) : fakeState;
  return { useTaskStore };
});

function renderRoot() {
  const rootRoute = createRootRoute({
    component: () => (
      <RootLayout>
        <Suspense fallback={null}>
          <Outlet />
        </Suspense>
      </RootLayout>
    ),
  });
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router as any} />
    </QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Notifications (#47)
// ---------------------------------------------------------------------------

describe("RootLayout: notifications", () => {
  beforeEach(() => {
    useNotificationStore.getState().clearAll();
    // Suppress the first-run gate in notification tests
    nextPreferencesResponse = { id: "post-onboarding-uuid" };
    localStorage.clear();
  });

  it("renders the bell with no badge when no notifications", async () => {
    renderRoot();
    await waitFor(() => {
      expect(screen.getByText(/MindForge/)).toBeInTheDocument();
    });
    const bell = screen.getByRole("button", { name: /notification/i });
    expect(bell).toBeInTheDocument();
    expect(screen.queryByText(/^\d+$/)).toBeNull();
  });

  it("shows the unread count when notifications arrive", async () => {
    renderRoot();
    await waitFor(() => {
      expect(screen.getByText(/MindForge/)).toBeInTheDocument();
    });

    useNotificationStore.getState().pushNotification({
      id: "x",
      type: "warning",
      message: "Draft ready",
      timestamp: new Date().toISOString(),
    });

    await waitFor(() => {
      expect(screen.getByText("1")).toBeInTheDocument();
    });
  });
});

// ---------------------------------------------------------------------------
// Clarification modal (#47)
// ---------------------------------------------------------------------------

describe("RootLayout: clarification modal", () => {
  beforeEach(() => {
    useNotificationStore.getState().clearAll();
    nextPreferencesResponse = { id: "post-onboarding-uuid" };
    localStorage.clear();
  });

  it("does not render a modal when no pending clarifications", async () => {
    renderRoot();
    await waitFor(() => {
      expect(screen.getByText(/MindForge/)).toBeInTheDocument();
    });
    expect(screen.queryByText(/needs clarification/i)).toBeNull();
  });

  it("renders a modal when a clarification is queued", async () => {
    renderRoot();
    await waitFor(() => {
      expect(screen.getByText(/MindForge/)).toBeInTheDocument();
    });

    useNotificationStore.getState().pushClarification({
      taskId: "task-42",
      agentName: "researcher",
      question: "Should I refund the full $19 or just the unused portion?",
      choices: ["full", "partial"],
    });

    await waitFor(() => {
      expect(
        screen.getByText(/Should I refund the full \$19/)
      ).toBeInTheDocument();
    });
  });

  it("dismisses + resolves on submit", async () => {
    const apiMod = await import("../../lib/api");
    renderRoot();
    await waitFor(() => {
      expect(screen.getByText(/MindForge/)).toBeInTheDocument();
    });

    useNotificationStore.getState().pushClarification({
      taskId: "task-42",
      agentName: "researcher",
      question: "Pick one",
      choices: ["a", "b"],
    });

    await waitFor(() => {
      expect(screen.getByText(/Pick one/)).toBeInTheDocument();
    });

    const choiceA = await screen.findByRole("button", { name: "a" });
    fireEvent.click(choiceA);

    const submitBtn = await screen.findByRole("button", { name: /submit|send/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(apiMod.submitClarification).toHaveBeenCalledWith("task-42", "a");
    });

    await waitFor(() => {
      expect(screen.queryByText(/Pick one/)).toBeNull();
    });
    expect(useNotificationStore.getState().pendingClarifications).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Onboarding gate (#46) — restored from the lost #68 merge
// ---------------------------------------------------------------------------

describe("RootLayout: onboarding gate", () => {
  beforeEach(() => {
    useNotificationStore.getState().clearAll();
    localStorage.clear();
    // First-run signal for these tests
    nextPreferencesResponse = { id: "" };
  });

  it("renders the wizard when preferences id is empty (first run)", async () => {
    renderRoot();
    // OnboardingWizard renders inside a fixed inset-0 with bg-black/60
    await waitFor(() => {
      const overlay = document.querySelector(".bg-black\\/60");
      expect(overlay).not.toBeNull();
    });
  });

  it("does NOT render the wizard when preferences id is a real value", async () => {
    nextPreferencesResponse = { id: "real-uuid-here" };
    renderRoot();
    await waitFor(() => {
      expect(screen.queryByText(/MindForge/)).toBeInTheDocument();
    });
    expect(document.querySelector(".bg-black\\/60")).toBeNull();
  });

  it("does NOT render the wizard when localStorage marks it dismissed", async () => {
    localStorage.setItem("mindforge:onboarding-dismissed", "true");
    renderRoot();
    await waitFor(() => {
      expect(screen.queryByText(/MindForge/)).toBeInTheDocument();
    });
    expect(document.querySelector(".bg-black\\/60")).toBeNull();
  });

  it("dismisses on Skip and persists across re-renders", async () => {
    const { unmount } = renderRoot();

    await waitFor(() => {
      expect(document.querySelector(".bg-black\\/60")).not.toBeNull();
    });

    const skip = screen.getByRole("button", { name: /skip/i });
    fireEvent.click(skip);

    await waitFor(() => {
      expect(document.querySelector(".bg-black\\/60")).toBeNull();
    });

    expect(localStorage.getItem("mindforge:onboarding-dismissed")).toBe("true");

    unmount();
    renderRoot();
    await waitFor(() => {
      expect(screen.queryByText(/MindForge/)).toBeInTheDocument();
    });
    expect(document.querySelector(".bg-black\\/60")).toBeNull();
  });
});
