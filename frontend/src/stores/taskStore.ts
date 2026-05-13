import { create } from "zustand";
import type { Task } from "../lib/api";

interface TaskState {
  tasks: Map<string, Task>;
  activeTaskId: string | null;
  wsDisconnected: boolean;
  setTasks: (tasks: Task[]) => void;
  upsertTask: (task: Task) => void;
  setActiveTask: (id: string | null) => void;
  setWsDisconnected: (v: boolean) => void;
  updateTaskStatus: (taskId: string, status: Task["status"]) => void;
}

export const useTaskStore = create<TaskState>((set) => ({
  tasks: new Map(),
  activeTaskId: null,
  wsDisconnected: false,

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
}));
