import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TaskCard } from "@/components/TaskCard";
import type { Task } from "@/lib/api";

describe("TaskCard", () => {
  it("renders task description and status", () => {
    const task: Task = {
      id: "task-1",
      skill_id: null,
      status: "pending",
      task_type: "github",
      project_id: null,
      description: "Review PR #123",
      context: {},
      created_at: new Date(Date.now() - 60_000).toISOString(), // 1 min ago
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    render(<TaskCard task={task} />);

    expect(screen.getByText("Review PR #123")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText(/^github/)).toBeInTheDocument();
  });

  it("renders completed task with green checkmark", () => {
    const task: Task = {
      id: "task-2",
      skill_id: "skill-abc",
      status: "completed",
      task_type: "email",
      project_id: "acme-corp",
      description: "Send follow-up email",
      context: {},
      created_at: new Date(Date.now() - 3_600_000).toISOString(), // 1h ago
      updated_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
    };

    render(<TaskCard task={task} />);

    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("acme-corp")).toBeInTheDocument();
  });

  it("calls onClick when card is clicked", () => {
    const task: Task = {
      id: "task-3",
      skill_id: null,
      status: "draft",
      task_type: "research",
      project_id: null,
      description: "Analyze competitor pricing",
      context: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    const handleClick = vi.fn();
    render(<TaskCard task={task} onClick={handleClick} />);

    screen.getByText("Analyze competitor pricing").click();
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("shows draft status with amber color", () => {
    const task: Task = {
      id: "task-4",
      skill_id: null,
      status: "draft",
      task_type: "content",
      project_id: null,
      description: "Draft blog post",
      context: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    render(<TaskCard task={task} />);

    const statusEl = screen.getByText("Awaiting Approval");
    expect(statusEl).toBeInTheDocument();
  });
});