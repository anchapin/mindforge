import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DraftReview } from "@/components/DraftReview";
import type { DraftContent } from "@/lib/api";
import React from "react";

const mockApproveTask = vi.fn();
const mockRejectTask = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return {
    ...actual,
    approveTask: (...args: unknown[]) => mockApproveTask(...args),
    rejectTask: (...args: unknown[]) => mockRejectTask(...args),
  };
});

vi.mock("@/stores/taskStore", () => ({
  useTaskStore: () => ({ updateTaskStatus: vi.fn() }),
}));

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe("DraftReview", () => {
  const defaultProps = {
    taskId: "task-1",
    draft: {
      subject: "Re: Your recent subscription",
      body: "Hi Sarah,\n\nThank you for reaching out.",
    } as DraftContent,
    approvalDeadlineIso: new Date(Date.now() + 2 * 3_600_000).toISOString(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders draft subject and body", () => {
    renderWithQuery(<DraftReview {...defaultProps} />);
    expect(screen.getByText(/Subject: Re: Your recent subscription/)).toBeInTheDocument();
    expect(screen.getByText(/Hi Sarah/)).toBeInTheDocument();
  });

  it("shows time remaining before deadline", () => {
    renderWithQuery(<DraftReview {...defaultProps} />);
    expect(screen.getByText(/\d+h \d+m left/)).toBeInTheDocument();
  });

  it("enters edit mode when 'Edit draft' is clicked", async () => {
    const user = userEvent.setup();
    renderWithQuery(<DraftReview {...defaultProps} />);
    await user.click(screen.getByText("Edit draft before approving"));
    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(screen.getByText("You modified this draft")).toBeInTheDocument();
  });

  it("calls approveTask when 'Approve & Send' is clicked from edit mode", async () => {
    const user = userEvent.setup();
    mockApproveTask.mockResolvedValueOnce(undefined);
    renderWithQuery(<DraftReview {...defaultProps} />);

    // First enter edit mode, then approve
    await user.click(screen.getByText("Edit draft before approving"));
    await user.click(screen.getByText("Approve & Send"));

    expect(mockApproveTask).toHaveBeenCalledWith(defaultProps.taskId, expect.any(Object));
  });

  it("shows reject textarea when 'Reject' is clicked", async () => {
    const user = userEvent.setup();
    renderWithQuery(<DraftReview {...defaultProps} />);
    await user.click(screen.getByText("Reject"));
    expect(screen.getByPlaceholderText("What should change?")).toBeInTheDocument();
  });

  it("requires min 10 chars for reject feedback", async () => {
    const user = userEvent.setup();
    mockRejectTask.mockResolvedValueOnce(undefined);
    renderWithQuery(<DraftReview {...defaultProps} />);
    await user.click(screen.getByText("Reject"));
    const textarea = screen.getByPlaceholderText("What should change?");
    await user.type(textarea, "Too short");
    expect(screen.getByText("Send feedback & rerun")).toBeDisabled();
  });

  it("enables send when reject feedback has 10+ chars", async () => {
    const user = userEvent.setup();
    mockRejectTask.mockResolvedValueOnce(undefined);
    renderWithQuery(<DraftReview {...defaultProps} />);
    await user.click(screen.getByText("Reject"));
    const textarea = screen.getByPlaceholderText("What should change?");
    await user.type(textarea, "This is long enough feedback");
    expect(screen.getByText("Send feedback & rerun")).toBeEnabled();
  });
});