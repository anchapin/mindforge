/**
 * TanStack Router configuration (#48).
 *
 * Code-defined routes (not file-based) so reviewers can see the full
 * route map at a glance. If/when the route count grows past ~10, switch
 * to file-based routes via the @tanstack/router-vite-plugin.
 *
 * Routes:
 *   /             -> redirect to /tasks
 *   /tasks        -> TaskTracker + ChatInterface (the dashboard)
 *   /skills       -> SkillLauncher
 *   /memory       -> MemoryViewer
 *   /preferences  -> placeholder (real component lands with #46/#47)
 */

import {
  createRootRoute,
  createRoute,
  createRouter,
  Outlet,
  redirect,
} from "@tanstack/react-router";
import { lazy, Suspense } from "react";
import { RootLayout } from "./components/layout/RootLayout";

// Lazy-load route components so each route is its own chunk.
// Reduces initial bundle size and isolates failures (a broken
// MemoryViewer doesn't block the dashboard).
const TasksPage = lazy(() => import("./routes/TasksPage"));
const SkillsPage = lazy(() => import("./routes/SkillsPage"));
const MemoryPage = lazy(() => import("./routes/MemoryPage"));
const PreferencesPage = lazy(() => import("./routes/PreferencesPage"));

function RouteFallback() {
  return (
    <div className="px-6 py-8 text-zinc-400 text-sm" role="status">
      Loading…
    </div>
  );
}

const rootRoute = createRootRoute({
  component: () => (
    <RootLayout>
      <Suspense fallback={<RouteFallback />}>
        <Outlet />
      </Suspense>
    </RootLayout>
  ),
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  // Redirect bare `/` -> `/tasks` so the dashboard is the default landing
  beforeLoad: () => {
    throw redirect({ to: "/tasks" });
  },
});

const tasksRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tasks",
  component: TasksPage,
});

const skillsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/skills",
  component: SkillsPage,
});

const memoryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/memory",
  component: MemoryPage,
});

const preferencesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/preferences",
  component: PreferencesPage,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  tasksRoute,
  skillsRoute,
  memoryRoute,
  preferencesRoute,
]);

export const router = createRouter({ routeTree });

// Module augmentation so useNavigate / Link infer routes correctly
declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
