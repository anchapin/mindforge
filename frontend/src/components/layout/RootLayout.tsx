/**
 * Root layout: header, nav, WS-disconnect banner, main content area (Outlet).
 *
 * Lifted out of App.tsx as part of #48 so each routed page gets the same
 * shell. Page-specific UI lives under <Outlet/>.
 */

import type { ReactNode } from "react";
import { Link, useLocation } from "@tanstack/react-router";
import { NotificationBell } from "../NotificationBell";
import { ClarificationModal } from "../ClarificationModal";
import { WSMessageHandler } from "../WSMessageHandler";
import { submitClarification } from "../../lib/api";
import { useTaskStore } from "../../stores/taskStore";
import { useNotificationStore } from "../../stores/notificationStore";

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

  // Notification + clarification wiring (#47).
  const notifications = useNotificationStore((s) => s.notifications);
  const markRead = useNotificationStore((s) => s.markRead);
  const markAllRead = useNotificationStore((s) => s.markAllRead);
  const dismissNotification = useNotificationStore((s) => s.dismiss);
  const pendingClarifications = useNotificationStore((s) => s.pendingClarifications);
  const resolveClarification = useNotificationStore((s) => s.resolveClarification);

  // Render at most one clarification modal at a time (head of queue).
  const activeClarification = pendingClarifications[0] ?? null;

  const handleClarificationSubmit = async (response: string) => {
    if (!activeClarification) return;
    try {
      await submitClarification(activeClarification.taskId, response);
    } catch (err) {
      // Surface the failure as a console error rather than silently dropping;
      // the user will retry from the next clarification request.
      // eslint-disable-next-line no-console
      console.error("Clarification submit failed:", err);
    } finally {
      resolveClarification(activeClarification.taskId);
    }
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
          <div className="flex items-center gap-4">
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
            <NotificationBell
              notifications={notifications}
              onMarkRead={markRead}
              onMarkAllRead={markAllRead}
              onDismiss={dismissNotification}
            />
          </div>
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

      {/* Clarification modal queue (#47). One at a time; the rest stay
          queued and surface as the user resolves each. */}
      {activeClarification && (
        <ClarificationModal
          taskId={activeClarification.taskId}
          agentName={activeClarification.agentName}
          question={activeClarification.question}
          choices={activeClarification.choices}
          onSubmit={handleClarificationSubmit}
          onCancel={() => resolveClarification(activeClarification.taskId)}
        />
      )}

      {/* Global WS dispatcher: turns websocket frames into store updates.
          Lifted out of TaskTracker so notifications fire on every route. */}
      <WSMessageHandler />
    </div>
  );
}
