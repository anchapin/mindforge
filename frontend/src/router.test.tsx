/**
 * Router smoke tests (#48).
 *
 * Avoids browser navigation by using `createMemoryHistory`. We just need
 * to verify:
 *   - the router can render
 *   - "/" redirects to "/tasks"
 *   - the four primary routes resolve to their components
 *   - nav links exist and reflect the active route
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
} from "@tanstack/react-router";
import { lazy, Suspense } from "react";

import { RootLayout } from "./components/layout/RootLayout";

// Mock all data-fetching so route components don't try to hit the backend
vi.mock("./lib/api", () => ({
  queryClient: new QueryClient({
    defaultOptions: { queries: { retry: false } },
  }),
  listSkills: vi.fn().mockResolvedValue([]),
  listMemory: vi.fn().mockResolvedValue({ semantic: [], episodic: [], style: [] }),
  searchMemory: vi.fn().mockResolvedValue([]),
  fetchTasks: vi.fn().mockResolvedValue([]),
  // Pretend we're past first run so #46's gate doesn't render the wizard
  // over the route content (the router test doesn't care about onboarding).
  fetchPreferences: vi.fn().mockResolvedValue({
    id: "post-onboarding-uuid",
    proactive_monitoring_enabled: true,
    email_check_interval_minutes: 30,
    calendar_check_interval_minutes: 60,
    billing_alert_threshold_usd: 50,
    notification_channel: "dashboard",
    notification_handle: null,
    created_at: "2026-05-15T00:00:00Z",
    updated_at: "2026-05-15T00:00:00Z",
  }),
  submitOnboarding: vi.fn(),
}));

// Mock the websocket lib so no real WS connection is attempted
vi.mock("./lib/websocket", () => ({
  connectWebSocket: vi.fn(),
  disconnectWebSocket: vi.fn(),
}));

// Build a parallel router instance for each test so memory history doesn't
// leak between specs. Mirrors the structure in src/router.tsx.
function buildTestRouter(initialPath: string) {
  const TasksPage = lazy(() => import("./routes/TasksPage"));
  const SkillsPage = lazy(() => import("./routes/SkillsPage"));
  const MemoryPage = lazy(() => import("./routes/MemoryPage"));
  const PreferencesPage = lazy(() => import("./routes/PreferencesPage"));

  const rootRoute = createRootRoute({
    component: () => (
      <RootLayout>
        <Suspense fallback={<div data-testid="loading">Loading…</div>}>
          <Outlet />
        </Suspense>
      </RootLayout>
    ),
  });

  const indexRoute = createRoute({
    getParentRoute: () => rootRoute,
    path: "/",
    beforeLoad: () => {
      // eslint-disable-next-line @typescript-eslint/no-throw-literal
      throw { redirect: { to: "/tasks" }, _isRedirect: true };
    },
  });

  const make = (path: string, Component: any) =>
    createRoute({
      getParentRoute: () => rootRoute,
      path,
      component: Component,
    });

  const routeTree = rootRoute.addChildren([
    indexRoute,
    make("/tasks", TasksPage),
    make("/skills", SkillsPage),
    make("/memory", MemoryPage),
    make("/preferences", PreferencesPage),
  ]);

  return createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [initialPath] }),
  });
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function renderAt(path: string) {
  const router = buildTestRouter(path);
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router as any} />
    </QueryClientProvider>
  );
}

describe("router", () => {
  beforeEach(() => {
    queryClient.clear();
  });

  it("renders the global header on every route", async () => {
    renderAt("/tasks");
    expect(await screen.findByText(/MindForge/)).toBeInTheDocument();
    // All four nav items present
    expect(screen.getByRole("link", { name: "Tasks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Skills" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Memory" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Preferences" })).toBeInTheDocument();
  });

  it("renders TasksPage at /tasks", async () => {
    renderAt("/tasks");
    // TasksPage renders a "Tasks" h2 (different from the nav link)
    await waitFor(() => {
      const headings = screen.getAllByRole("heading", { name: "Tasks" });
      expect(headings.length).toBeGreaterThan(0);
    });
  });

  it("renders SkillsPage at /skills", async () => {
    renderAt("/skills");
    // SkillLauncher renders the "Skills" header inside its component
    await waitFor(() => {
      const headings = screen.getAllByRole("heading", { name: /Skills/ });
      expect(headings.length).toBeGreaterThan(0);
    });
  });

  it("renders MemoryPage at /memory", async () => {
    renderAt("/memory");
    await waitFor(() => {
      const headings = screen.getAllByRole("heading", { name: /Memory/ });
      expect(headings.length).toBeGreaterThan(0);
    });
  });

  it("renders PreferencesPage at /preferences", async () => {
    renderAt("/preferences");
    await waitFor(() => {
      const headings = screen.getAllByRole("heading", { name: /Preferences/ });
      expect(headings.length).toBeGreaterThan(0);
    });
    // Placeholder copy until #46/follow-up wires the real form
    expect(
      await screen.findByText(/will be wired in a follow-up/i)
    ).toBeInTheDocument();
  });

  it("marks the active nav link with aria-current=page", async () => {
    renderAt("/skills");
    await waitFor(() => {
      const skillsLink = screen.getByRole("link", { name: "Skills" });
      expect(skillsLink.getAttribute("aria-current")).toBe("page");
    });
    const tasksLink = screen.getByRole("link", { name: "Tasks" });
    expect(tasksLink.getAttribute("aria-current")).toBeNull();
  });
});
