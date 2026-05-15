/**
 * TaskDebug (#49) — verifies the node-walk renders against a fake task
 * payload with skill_execution_context.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { TaskDebug } from "./TaskDebug";

vi.mock("@/lib/api", () => ({
  getTask: vi.fn(),
}));

import { getTask } from "@/lib/api";

function renderWithClient() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <TaskDebug taskId="abc12345-ef" />
    </QueryClientProvider>
  );
}

describe("TaskDebug", () => {
  it("renders an empty-state message when the task didn't run as a skill", async () => {
    (getTask as any).mockResolvedValue({
      id: "abc12345-ef",
      description: "do a thing",
      status: "completed",
      context: {},
      created_at: "",
      updated_at: "",
      completed_at: "",
      skill_id: null,
      task_type: "general",
      project_id: null,
    });
    renderWithClient();
    await waitFor(() => {
      expect(screen.getByText(/didn't run as a skill/)).toBeInTheDocument();
    });
  });

  it("renders one entry per completed node with status + output", async () => {
    (getTask as any).mockResolvedValue({
      id: "abc12345-ef",
      description: "summarize commits",
      status: "completed",
      context: {
        skill_execution_context: {
          skill_id: "github-summary",
          node_id: "draft",
          nodes_completed: ["fetch", "analyze", "draft"],
          scratch: {
            fetch: {
              status: "success",
              output: {
                text: "Pulled 12 commits from main",
                tools_offered: ["github_api"],
              },
            },
            analyze: {
              status: "success",
              output: { text: "3 PRs merged, 2 hotfixes" },
            },
            draft: {
              status: "failure",
              error: "LLM timeout",
            },
          },
        },
      },
      created_at: "",
      updated_at: "",
      completed_at: "",
      skill_id: "github-summary",
      task_type: "github",
      project_id: null,
    });
    renderWithClient();

    // Header badges
    await waitFor(() => {
      expect(screen.getByText("github-summary")).toBeInTheDocument();
    });

    // All three nodes appear in order
    expect(screen.getByText(/1\. fetch/)).toBeInTheDocument();
    expect(screen.getByText(/2\. analyze/)).toBeInTheDocument();
    expect(screen.getByText(/3\. draft/)).toBeInTheDocument();

    // Outputs surface
    expect(screen.getByText(/Pulled 12 commits/)).toBeInTheDocument();
    expect(screen.getByText(/3 PRs merged/)).toBeInTheDocument();

    // Failure error block surfaces
    expect(screen.getByText(/LLM timeout/)).toBeInTheDocument();

    // Tools-offered hint surfaces
    expect(screen.getByText(/Tools offered: github_api/)).toBeInTheDocument();
  });

  it("renders an error message when getTask fails", async () => {
    (getTask as any).mockRejectedValue(new Error("not found"));
    renderWithClient();
    await waitFor(() => {
      expect(screen.getByText(/Could not load task/)).toBeInTheDocument();
    });
  });
});
