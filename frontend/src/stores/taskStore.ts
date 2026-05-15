import { create } from "zustand";
import type { Task } from "../lib/api";
import { getLastSeq } from "../lib/websocket";

interface TaskState {
  tasks: Map<string, Task>;
  activeTaskId: string | null;
  wsDisconnected: boolean;
  lastSeenSeq: number;          // #106: last server seq processed
  correlationIds: Set<string>;  // #109: recent correlation_ids for tracing
  setTasks: (tasks: Task[]) => void;
  upsertTask: (task: Task) => void;
  setActiveTask: (id: string | null) => void;
  setWsDisconnected: (v: boolean) => void;
  updateTaskStatus: (taskId: string, status: Task["status"]) => void;
  setLastSeenSeq: (seq: number) => void;   // #106
  trackCorrelationId: (id: string) => void; // #109
}

export const useTaskStore = create<TaskState>((set) => ({
  tasks: new Map(),
  activeTaskId: null,
  wsDisconnected: false,
  lastSeenSeq: 0,          // #106: start at 0 so server replays all on first connect
  correlationIds: new Set(),

  setTasks: (tasks) =>
    set({ tasks: new Map(tasks.map((t) => [t.id, t])) }),

  upsertTask: (task) =>
    set((state) => {
      const next = new Map(state.tasks);
      next.set(task.id, task);
      return { tasks: next };
    }),

  setActiveTask: (id) => set({ activeTaskId: id }),

  setWsDisconnected: (v) => set({ wsDisconnected: v }),

  updateTaskStatus: (taskId, status) =>
    set((state) => {
      const task = state.tasks.get(taskId);
      if (!task) return state;
      const next = new Map(state.tasks);
      next.set(taskId, { ...task, status });
      return { tasks: next };
    }),

  // #106: update lastSeenSeq when processing a server seq
  setLastSeenSeq: (seq) => set({ lastSeenSeq: Math.max(seq, getLastSeq()) }),

  // #109: keep last 50 correlation_ids for log tracing
  trackCorrelationId: (id) =>
    set((state) => {
      const next = new Set(state.correlationIds);
      next.add(id);
      // Trim to avoid unbounded growth
      if (next.size > 50) {
        const arr = Array.from(next);
        next.delete(arr[0]);
      }
      return { correlationIds: next };
    }),
}));
