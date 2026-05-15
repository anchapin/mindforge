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

// ---------------------------------------------------------------------------
// Clarification protocol (#47)
// ---------------------------------------------------------------------------

export async function submitClarification(
  taskId: string,
  response: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}/clarification`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision: response }),
  });
  if (!res.ok) throw new Error(`Clarification submission failed: ${res.statusText}`);
}

// ---------------------------------------------------------------------------
// Preferences + onboarding (#46)
// ---------------------------------------------------------------------------

export interface Preferences {
  id: string;
  proactive_monitoring_enabled: boolean;
  email_check_interval_minutes: number;
  calendar_check_interval_minutes: number;
  billing_alert_threshold_usd: number;
  notification_channel: string;
  notification_handle: string | null;
  // True once POST /api/onboarding (or /api/onboarding/skip) has fired.
  // Frontend first-run gate keys off this — see #72 for why the previous
  // `id === ""` signal didn't work in production.
  onboarding_completed: boolean;
  created_at: string;
  updated_at: string;
}

export async function fetchPreferences(): Promise<Preferences> {
  const res = await fetch(`${API_BASE}/api/preferences/`);
  if (!res.ok) throw new Error(`Failed to fetch preferences: ${res.statusText}`);
  return res.json();
}

/** Partial-update payload for PUT /api/preferences. */
export interface PreferencesUpdate {
  proactive_monitoring_enabled?: boolean;
  email_check_interval_minutes?: number;
  calendar_check_interval_minutes?: number;
  billing_alert_threshold_usd?: number;
  notification_channel?: string;
  notification_handle?: string | null;
}

export async function updatePreferences(
  payload: PreferencesUpdate,
): Promise<{ status: string; preferences: Preferences }> {
  const res = await fetch(`${API_BASE}/api/preferences/`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to update preferences: ${res.statusText}`);
  return res.json();
}

export interface OnboardingPayload {
  writing_style: {
    tone?: string;
    sentence_length?: string;
    first_person?: string;
    signature_phrases?: string[];
    greeting_style?: string;
    signoff_style?: string;
  };
  integrations: Array<{
    app_name: string;
    token: string;
    permissions?: string[];
    allowed_agents?: string[];
  }>;
}

export async function submitOnboarding(payload: OnboardingPayload): Promise<void> {
  const res = await fetch(`${API_BASE}/api/onboarding/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Onboarding submission failed: ${res.statusText}`);
}

/**
 * Mark onboarding as complete without writing any profile/integration data.
 * Used by the wizard's "Skip" button so we don't keep prompting the user.
 */
export async function submitOnboardingSkip(): Promise<void> {
  const res = await fetch(`${API_BASE}/api/onboarding/skip`, { method: "POST" });
  if (!res.ok) throw new Error(`Onboarding skip failed: ${res.statusText}`);
}

// ---------------------------------------------------------------------------
// Integrations (#93)
// ---------------------------------------------------------------------------

export interface Integration {
  id: string;
  app_name: string;
  status: "active" | "revoked" | "error" | "expired";
  permissions: string[];
  allowed_agents: string[];
  last_sync_at?: string;
  created_at: string;
  updated_at: string;
}

export async function listIntegrations(): Promise<Integration[]> {
  const res = await fetch(`${API_BASE}/api/integrations/`);
  if (!res.ok) throw new Error(`Failed to list integrations: ${res.statusText}`);
  return res.json();
}

export async function createIntegration(payload: {
  app_name: string;
  token: string;
  permissions?: string[];
  allowed_agents?: string[];
}): Promise<Integration> {
  const res = await fetch(`${API_BASE}/api/integrations/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to create integration: ${res.statusText}`);
  return res.json();
}

export async function deleteIntegration(id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/integrations/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to delete integration: ${res.statusText}`);
}

export async function updateIntegration(
  id: string,
  payload: { permissions?: string[]; allowed_agents?: string[] },
): Promise<Integration> {
  const res = await fetch(`${API_BASE}/api/integrations/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Failed to update integration: ${res.statusText}`);
  return res.json();
}

export interface IntegrationTestResult {
  success: boolean;
  message: string;
  probed: boolean;
}

export async function testIntegration(id: string): Promise<IntegrationTestResult> {
  const res = await fetch(`${API_BASE}/api/integrations/${id}/test`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`Failed to test integration: ${res.statusText}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Skill editor (#49)
// ---------------------------------------------------------------------------

export interface SkillNode {
  id: string;
  agent?: string;
  goal?: string;
  requires_approval?: boolean;
  [key: string]: unknown;
}

export interface SkillEdge {
  from: string;
  to: string;
  condition?: string;
}

export interface SkillGraphPreview {
  nodes: SkillNode[];
  edges: SkillEdge[];
}

export interface SkillValidationResult {
  valid: boolean;
  errors: string[];
  graph: SkillGraphPreview | null;
}

export async function validateSkillYaml(
  yamlContent: string,
): Promise<SkillValidationResult> {
  const res = await fetch(`${API_BASE}/api/skills/validate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml_content: yamlContent }),
  });
  if (!res.ok) {
    throw new Error(`Skill validation request failed: ${res.statusText}`);
  }
  return res.json();
}
