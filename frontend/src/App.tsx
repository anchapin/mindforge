/**
 * App root: mounts the QueryClient and the TanStack Router (#48).
 *
 * Page-level UI was extracted into `src/routes/*` and `src/router.tsx`.
 * If you're looking for the dashboard, see `routes/TasksPage.tsx`.
 */

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { queryClient } from "./lib/api";
import { router } from "./router";

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
