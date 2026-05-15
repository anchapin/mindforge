/**
 * Notification store (#47).
 *
 * Receives translated WS events (draft_ready, task_failed, budget warnings,
 * etc.) from WSMessageHandler and exposes them to the NotificationBell in
 * the header. Also doubles as the clarification-request inbox so the
 * RootLayout can pop a single ClarificationModal at a time.
 *
 * Persistence: notifications live in component memory only — clearing via
 * a refresh is fine (each WS reconnect re-syncs state). If we ever want
 * historical notifications, persist via the backend, not localStorage.
 */

import { create } from "zustand";

export interface Notification {
  id: string;
  type: "info" | "warning" | "error" | "success";
  message: string;
  timestamp: string;
  read: boolean;
}

export interface ClarificationRequest {
  taskId: string;
  agentName: string;
  question: string;
  choices: string[];
  // Server-supplied deadline; informational
  deadlineIso?: string;
}

interface NotificationState {
  notifications: Notification[];
  // Queue of pending clarification requests; we render the head of this list.
  // More than one in flight at once is rare but should not be silently lost.
  pendingClarifications: ClarificationRequest[];

  pushNotification: (n: Omit<Notification, "read"> & { read?: boolean }) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  dismiss: (id: string) => void;

  pushClarification: (req: ClarificationRequest) => void;
  resolveClarification: (taskId: string) => void;
  clearAll: () => void;
}

export const useNotificationStore = create<NotificationState>((set) => ({
  notifications: [],
  pendingClarifications: [],

  pushNotification: (n) =>
    set((state) => ({
      notifications: [
        { read: false, ...n },
        ...state.notifications.filter((existing) => existing.id !== n.id),
      ].slice(0, 100),  // bound the in-memory list
    })),

  markRead: (id) =>
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, read: true } : n,
      ),
    })),

  markAllRead: () =>
    set((state) => ({
      notifications: state.notifications.map((n) => ({ ...n, read: true })),
    })),

  dismiss: (id) =>
    set((state) => ({
      notifications: state.notifications.filter((n) => n.id !== id),
    })),

  pushClarification: (req) =>
    set((state) => {
      // De-dup by taskId — a redelivered WS message shouldn't queue twice
      const existing = state.pendingClarifications.find((c) => c.taskId === req.taskId);
      if (existing) return state;
      return { pendingClarifications: [...state.pendingClarifications, req] };
    }),

  resolveClarification: (taskId) =>
    set((state) => ({
      pendingClarifications: state.pendingClarifications.filter(
        (c) => c.taskId !== taskId,
      ),
    })),

  clearAll: () =>
    set(() => ({ notifications: [], pendingClarifications: [] })),
}));
