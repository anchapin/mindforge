import { QueryClient } from "@tanstack/react-query";

export const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

export interface Task {
  id: string;
  skill_id: string | null;
  status: "pending" | "running" | "draft" | "approved" | "executing" | "completed" | "failed";
  task_type: string;
  project_id: string | null;
  description: string;
  context: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface DraftContent {
  subject?: string;
  body: string;
  [key: string]: unknown;
}

export async function listTasks(params?: { status?: string; project_id?: string }): Promise<Task[]> {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.project_id) qs.set("project_id", params.project_id);
  const res = await fetch(`${API_BASE}/api/tasks/?${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch tasks: ${res.statusText}`);
  return res.json();
}

export async function createTask(description: string, projectId?: string): Promise<Task> {
  const res = await fetch(`${API_BASE}/api/tasks/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description, project_id: projectId }),
  });
  if (!res.ok) throw new Error(`Failed to create task: ${res.statusText}`);
  return res.json();
}

export async function getTask(taskId: string): Promise<Task> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}`);
  if (!res.ok) throw new Error(`Failed to fetch task: ${res.statusText}`);
  return res.json();
}

export async function approveTask(taskId: string, editedContent?: DraftContent): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ edited_content: editedContent ?? null }),
  });
  if (!res.ok) throw new Error(`Failed to approve task: ${res.statusText}`);
}

export async function rejectTask(taskId: string, feedback: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}/reject`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
  if (!res.ok) throw new Error(`Failed to reject task: ${res.statusText}`);
}

export async function cancelTask(taskId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}/cancel`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to cancel task: ${res.statusText}`);
}

export interface Skill {
  id: string;
  name: string;
  description?: string;
  version?: string;
  trigger?: string;
  created_at: string;
}

export async function listSkills(): Promise<Skill[]> {
  const res = await fetch(`${API_BASE}/api/skills/`);
  if (!res.ok) throw new Error(`Failed to list skills: ${res.statusText}`);
  return res.json();
}

export async function getSkill(skillId: string): Promise<Skill> {
  const res = await fetch(`${API_BASE}/api/skills/${skillId}`);
  if (!res.ok) throw new Error(`Failed to get skill: ${res.statusText}`);
  return res.json();
}

export interface MemoryEntry {
  id: string;
  memory_type: string;
  content: string;
  project_id?: string;
  created_at: string;
}

export async function listMemory(): Promise<{
  semantic: MemoryEntry[];
  episodic: MemoryEntry[];
  style: MemoryEntry[];
}> {
  const res = await fetch(`${API_BASE}/api/memory/`);
  if (!res.ok) throw new Error(`Failed to list memory: ${res.statusText}`);
  return res.json();
}

export async function searchMemory(query: string): Promise<MemoryEntry[]> {
  const res = await fetch(`${API_BASE}/api/memory/search?q=${encodeURIComponent(query)}`);
  if (!res.ok) throw new Error(`Failed to search memory: ${res.statusText}`);
  return res.json();
}
