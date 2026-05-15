/**
 * Root layout: header, nav, WS-disconnect banner, main content area (Outlet).
 *
 * Lifted out of App.tsx as part of #48 so each routed page gets the same
 * shell. Page-specific UI lives under <Outlet/>.
 */

import { useState, type ReactNode } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { OnboardingWizard } from "../OnboardingWizard";
import { fetchPreferences } from "../../lib/api";
import {
  markOnboardingDismissed,
  shouldShowOnboarding,
} from "../../lib/firstRun";
import { useTaskStore } from "../../stores/taskStore";

interface NavItem {
  to: string;
  label: string;
}

const NAV_ITEMS: NavItem[] = [
  { to: "/tasks", label: "Tasks" },
  { to: "/skills", label: "Skills" },
  { to: "/memory", label: "Memory" },
  { to: "/preferences", label: "Preferences" },
];

export function RootLayout({ children }: { children: ReactNode }) {
  const wsDisconnected = useTaskStore((s) => s.wsDisconnected);
  const location = useLocation();
  // First-run gate (#46): GET /api/preferences. The backend returns
  // { id: "" } when the singleton hasn't been created yet — that's our
  // signal to render the wizard. The wizard is dismissed permanently for
  // the browser via localStorage AND in component state (because
  // localStorage writes don't trigger React re-renders by themselves).
  const { data: prefs, isLoading: prefsLoading } = useQuery({
    queryKey: ["preferences"],
    queryFn: fetchPreferences,
    staleTime: 5 * 60 * 1000,
    retry: 0,
  });

  const [dismissedThisSession, setDismissedThisSession] = useState(false);

  const showOnboarding =
    !dismissedThisSession &&
    shouldShowOnboarding({
      preferencesId: prefs?.id,
      preferencesLoading: prefsLoading,
    });

  const handleOnboardingDismiss = () => {
    markOnboardingDismissed();        // persist for future page loads
    setDismissedThisSession(true);    // hide immediately, this render
  };

  return (
    <div className="flex min-h-screen flex-col bg-zinc-900 text-zinc-100">
      {/* Header */}
      <header className="border-b border-zinc-800 bg-zinc-900/80 sticky top-0 z-10 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <h1 className="text-xl font-bold tracking-tight">
            MindForge{" "}
            <span className="text-zinc-500 text-sm font-normal">AI Team</span>
          </h1>
          <nav aria-label="Primary">
            <ul className="flex gap-4 text-sm text-zinc-400">
              {NAV_ITEMS.map((item) => {
                const isActive = location.pathname.startsWith(item.to);
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      className={
                        isActive
                          ? "text-zinc-100 font-medium"
                          : "hover:text-zinc-200 transition"
                      }
                      aria-current={isActive ? "page" : undefined}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </div>
      </header>

      {/* WS disconnect banner — global, every route */}
      {wsDisconnected && (
        <div
          className="bg-amber-900/30 border-b border-amber-700 px-6 py-2 text-sm text-amber-300"
          role="status"
          aria-live="polite"
        >
          Live updates paused — your task state is up to date as of a few minutes ago.
        </div>
      )}

      {/* Routed content */}
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-8 space-y-8">
        {children}
      </main>

      {/* First-run onboarding gate (#46). Rendered as a modal overlay so it
          sits above whatever route is active. */}
      {showOnboarding && (
        <OnboardingWizard
          onComplete={handleOnboardingDismiss}
          onSkip={handleOnboardingDismiss}
        />
      )}
    </div>
  );
}
