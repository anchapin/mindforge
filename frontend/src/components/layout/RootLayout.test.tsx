/**
 * Notification-bell + clarification-modal integration tests for RootLayout (#47).
 *
 * Notes:
 *  - Mocks the websocket lib so no real connection is attempted.
 *  - Uses memory-history router so we can mount RootLayout in isolation.
 *  - The notification store is reset between tests to avoid cross-test bleed.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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

vi.mock("../../lib/api", () => ({
  submitClarification: vi.fn().mockResolvedValue(undefined),
}));

// Avoid the real WS singleton trying to connect
vi.mock("../../lib/websocket", () => ({
  getGlobalWS: () => ({ subscribe: () => () => {} }),
}));

vi.mock("../../stores/taskStore", () => {
  // Both call patterns must be supported:
  //   useTaskStore((s) => s.wsDisconnected)        -> RootLayout
  //   useTaskStore()                                -> WSMessageHandler destructure
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

describe("RootLayout: notifications", () => {
  beforeEach(() => {
    useNotificationStore.getState().clearAll();
  });

  it("renders the bell with no badge when no notifications", async () => {
    renderRoot();
    await waitFor(() => {
      expect(screen.getByText(/MindForge/)).toBeInTheDocument();
    });
    // Bell button is always present
    const bell = screen.getByRole("button", { name: /notification/i });
    expect(bell).toBeInTheDocument();
    // No unread count badge text
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

    // Badge with "1"
    await waitFor(() => {
      expect(screen.getByText("1")).toBeInTheDocument();
    });
  });
});

describe("RootLayout: clarification modal", () => {
  beforeEach(() => {
    useNotificationStore.getState().clearAll();
  });

  it("does not render a modal when no pending clarifications", async () => {
    renderRoot();
    await waitFor(() => {
      expect(screen.getByText(/MindForge/)).toBeInTheDocument();
    });
    // ClarificationModal renders an h2 with the agent name + "needs clarification"
    expect(
      screen.queryByText(/needs clarification/i)
    ).toBeNull();
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

    // Wait for modal
    await waitFor(() => {
      expect(screen.getByText(/Pick one/)).toBeInTheDocument();
    });

    // Click choice 'a' (ClarificationModal renders choices as buttons)
    const choiceA = await screen.findByRole("button", { name: "a" });
    fireEvent.click(choiceA);

    // Submit button (look for one labeled "Submit" or "Send")
    const submitBtn = await screen.findByRole("button", { name: /submit|send/i });
    fireEvent.click(submitBtn);

    // API was called with the response
    await waitFor(() => {
      expect(apiMod.submitClarification).toHaveBeenCalledWith("task-42", "a");
    });

    // Modal removed (no more "Pick one" text)
    await waitFor(() => {
      expect(screen.queryByText(/Pick one/)).toBeNull();
    });
    // Queue empty
    expect(useNotificationStore.getState().pendingClarifications).toHaveLength(0);
  });
});
