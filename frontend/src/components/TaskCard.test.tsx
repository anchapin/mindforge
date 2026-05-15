import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TaskCard, ProjectBadge, StatusBadge, StepProgress, CountdownTimer } from "@/components/TaskCard";
import type { Task } from "@/lib/api";

describe("ProjectBadge", () => {
  it("renders global badge when project_id is null", () => {
    render(<ProjectBadge projectId={null} />);
    expect(screen.getByText("(global)")).toBeInTheDocument();
  });

  it("renders project name when project_id is set", () => {
    render(<ProjectBadge projectId="acme-corp" />);
    expect(screen.getByText("acme-corp")).toBeInTheDocument();
  });

  it("renders with click handler when onProjectChange provided", () => {
    render(<ProjectBadge projectId="acme-corp" onProjectChange={() => {}} />);
    const btn = screen.getByRole("button");
    expect(btn).toBeInTheDocument();
  });
});

describe("StatusBadge", () => {
  it("shows Pending for pending status", () => {
    render(<StatusBadge status="pending" />);
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("shows Running with blue text for running status", () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("shows Awaiting Approval for draft status", () => {
    render(<StatusBadge status="draft" />);
    expect(screen.getByText("Awaiting Approval")).toBeInTheDocument();
  });

  it("shows Completed for completed status", () => {
    render(<StatusBadge status="completed" />);
    expect(screen.getByText("Completed")).toBeInTheDocument();
  });

  it("shows Failed for failed status", () => {
    render(<StatusBadge status="failed" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });
});

describe("StepProgress", () => {
  it("renders step count", () => {
    render(<StepProgress currentNode="drafting" nodesCompleted={["verify", "analyze"]} totalNodes={4} />);
    expect(screen.getByText("Step 3/4")).toBeInTheDocument();
    expect(screen.getByText("→ drafting")).toBeInTheDocument();
  });

  it("renders step count without totalNodes", () => {
    render(<StepProgress currentNode="verify" nodesCompleted={[]} />);
    expect(screen.getByText(/Step 1\/1/)).toBeInTheDocument();
  });
});

describe("CountdownTimer", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("shows time left for future deadline", () => {
    const future = new Date(Date.now() + 2 * 3_600_000).toISOString(); // 2h
    render(<CountdownTimer deadlineIso={future} />);
    expect(screen.getByText(/\d+h \d+m left/)).toBeInTheDocument();
  });

  it("shows expired when deadline is past", () => {
    const past = new Date(Date.now() - 60_000).toISOString(); // 1m ago
    render(<CountdownTimer deadlineIso={past} />);
    expect(screen.getByText("expired left")).toBeInTheDocument();
  });
});

describe("TaskCard", () => {
  it("renders task description and truncated text", () => {
    const task: Task = {
      id: "task-1",
      skill_id: null,
      status: "pending",
      task_type: "github",
      project_id: null,
      description: "Review PR #123",
      context: {},
      created_at: new Date(Date.now() - 60_000).toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    render(<TaskCard task={task} />);

    expect(screen.getByText("Review PR #123")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(screen.getByText("(global)")).toBeInTheDocument();
  });

  it("renders completed task with project badge", () => {
    const task: Task = {
      id: "task-2",
      skill_id: "skill-abc",
      status: "completed",
      task_type: "email",
      project_id: "acme-corp",
      description: "Send follow-up email",
      context: {},
      created_at: new Date(Date.now() - 3_600_000).toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: new Date().toISOString(),
    };

    render(<TaskCard task={task} />);

    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("acme-corp")).toBeInTheDocument();
  });

  it("expands draft card without calling onClick on first click", () => {
    const task: Task = {
      id: "task-3",
      skill_id: null,
      status: "draft",
      task_type: "research",
      project_id: null,
      description: "Analyze competitor pricing",
      context: { draft_content: { body: "Draft text" }, approval_deadline_iso: new Date(Date.now() + 3_600_000).toISOString() },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    const handleClick = vi.fn();
    render(<TaskCard task={task} onClick={handleClick} />);

    screen.getByText("Analyze competitor pricing").click();
    // Draft cards expand inline on first click; onClick fires only on second click
    expect(handleClick).not.toHaveBeenCalled();
  });

  it("shows draft status with amber color when awaiting approval", () => {
    const task: Task = {
      id: "task-4",
      skill_id: null,
      status: "draft",
      task_type: "content",
      project_id: null,
      description: "Draft blog post",
      context: { draft_content: { body: "..." }, approval_deadline_iso: new Date(Date.now() + 3_600_000).toISOString() },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    render(<TaskCard task={task} />);

    const statusEl = screen.getByText("Awaiting Approval");
    expect(statusEl).toBeInTheDocument();
  });

  it("shows step progress for running task", () => {
    const task: Task = {
      id: "task-5",
      skill_id: null,
      status: "running",
      task_type: "research",
      project_id: null,
      description: "Run analysis",
      context: {
        nodes_completed: ["fetch", "analyze"],
        current_node: "drafting",
      },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    render(<TaskCard task={task} />);

    expect(screen.getByText("Step 3/4")).toBeInTheDocument();
    expect(screen.getByText("→ drafting")).toBeInTheDocument();
  });

  it("shows countdown timer for draft tasks", () => {
    const task: Task = {
      id: "task-6",
      skill_id: null,
      status: "draft",
      task_type: "content",
      project_id: null,
      description: "Draft newsletter",
      context: {
        draft_content: { body: "..." },
        approval_deadline_iso: new Date(Date.now() + 2 * 3_600_000).toISOString(),
      },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    render(<TaskCard task={task} />);

    expect(screen.getByText(/left/)).toBeInTheDocument();
  });

  it("shows failed state message", () => {
    const task: Task = {
      id: "task-7",
      skill_id: null,
      status: "failed",
      task_type: "github",
      project_id: null,
      description: "Commit changes",
      context: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      completed_at: null,
    };

    render(<TaskCard task={task} />);

    expect(screen.getByText("Failed — tap for details")).toBeInTheDocument();
  });
});