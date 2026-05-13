import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ClarificationModal } from "@/components/ClarificationModal";
import type { DraftContent } from "@/lib/api";
import React from "react";

const mockApproveTask = vi.fn();

// Mock API
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return {
    ...actual,
    approveTask: (...args: unknown[]) => mockApproveTask(...args),
  };
});

// Mock task store
vi.mock("@/stores/taskStore", () => ({
  useTaskStore: () => ({ updateTaskStatus: vi.fn() }),
}));

// Mock React Query
vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual("@tanstack/react-query");
  return {
    ...actual,
    useMutation: vi.fn(() => ({
      mutate: vi.fn(),
      isPending: false,
    })),
    useQueryClient: vi.fn(() => ({
      invalidateQueries: vi.fn(),
    })),
  };
});

function renderWithQuery(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

describe("ClarificationModal", () => {
  const defaultProps = {
    taskId: "task-1",
    agentName: "COO Agent",
    question: "Should I offer a refund, replacement, or store credit?",
    choices: ["Refund", "Replacement", "Store credit"] as string[],
    onSubmit: vi.fn(),
    onCancel: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the modal with agent name and question", () => {
    renderWithQuery(<ClarificationModal {...defaultProps} />);

    expect(screen.getByText("COO Agent needs your input")).toBeInTheDocument();
    expect(screen.getByText("Should I offer a refund, replacement, or store credit?")).toBeInTheDocument();
  });

  it("renders choice buttons", () => {
    renderWithQuery(<ClarificationModal {...defaultProps} />);

    expect(screen.getByRole("button", { name: "Refund" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replacement" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Store credit" })).toBeInTheDocument();
  });

  it("calls onSubmit with choice when a button is clicked", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ClarificationModal {...defaultProps} />);

    await user.click(screen.getByRole("button", { name: "Refund" }));

    expect(defaultProps.onSubmit).toHaveBeenCalledWith("Refund");
  });

  it("calls onSubmit with free-form text when submitted", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ClarificationModal {...defaultProps} />);

    const textarea = screen.getByPlaceholderText("Or tell me in your own words...");
    await user.type(textarea, "I prefer a replacement");

    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(defaultProps.onSubmit).toHaveBeenCalledWith("I prefer a replacement");
  });

  it("calls onCancel when cancel button is clicked", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ClarificationModal {...defaultProps} />);

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(defaultProps.onCancel).toHaveBeenCalled();
  });

  it("does not submit empty free-form text", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ClarificationModal {...defaultProps} />);

    const textarea = screen.getByPlaceholderText("Or tell me in your own words...");
    await user.type(textarea, "   ");

    await user.click(screen.getByRole("button", { name: "Submit" }));

    expect(defaultProps.onSubmit).not.toHaveBeenCalled();
  });

  it("shows close button", () => {
    renderWithQuery(<ClarificationModal {...defaultProps} />);

    // Should have an X or close button
    const closeButton = screen.getByRole("button", { name: /close/i });
    expect(closeButton).toBeInTheDocument();
  });
});