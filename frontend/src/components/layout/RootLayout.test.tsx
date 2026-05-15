/**
 * Onboarding-gate integration tests for RootLayout (#46).
 *
 * The gate mounts when GET /api/preferences returns { id: "" } AND the user
 * hasn't dismissed it in localStorage. We verify both halves and the
 * persistence of the dismissal across re-renders.
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

// Module-level state for the mocked fetch
let nextPreferencesResponse: { id: string } = { id: "" };

vi.mock("../../lib/api", () => ({
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

// Avoid accidental WS/store side effects
vi.mock("../../stores/taskStore", () => ({
  useTaskStore: (selector: any) => selector({ wsDisconnected: false }),
}));

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
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router as any} />
    </QueryClientProvider>
  );
}

describe("RootLayout onboarding gate", () => {
  beforeEach(() => {
    localStorage.clear();
    nextPreferencesResponse = { id: "" };
  });

  it("renders the wizard when preferences id is empty (first run)", async () => {
    renderRoot();
    // OnboardingWizard renders an h2 / heading; the role-based query is
    // brittle to the wizard's exact markup, so probe by an element with the
    // backdrop class instead.
    await waitFor(() => {
      // The wizard container has fixed inset-0 with bg-black/60
      const overlay = document.querySelector(".bg-black\\/60");
      expect(overlay).not.toBeNull();
    });
  });

  it("does NOT render the wizard when preferences id is a real value", async () => {
    nextPreferencesResponse = { id: "real-uuid-here" };
    renderRoot();
    // Wait long enough for the prefs query to settle
    await waitFor(() => {
      expect(screen.queryByText(/MindForge/)).toBeInTheDocument();
    });
    // No wizard
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

    // Wait for wizard
    await waitFor(() => {
      expect(document.querySelector(".bg-black\\/60")).not.toBeNull();
    });

    // OnboardingWizard's Skip button (component renders 'Skip' on step 1)
    const skip = screen.getByRole("button", { name: /skip/i });
    fireEvent.click(skip);

    // Wizard should disappear
    await waitFor(() => {
      expect(document.querySelector(".bg-black\\/60")).toBeNull();
    });

    // localStorage flag set
    expect(localStorage.getItem("mindforge:onboarding-dismissed")).toBe("true");

    // Re-mount: wizard stays gone (even though prefs.id is still "")
    unmount();
    renderRoot();
    await waitFor(() => {
      expect(screen.queryByText(/MindForge/)).toBeInTheDocument();
    });
    expect(document.querySelector(".bg-black\\/60")).toBeNull();
  });
});
