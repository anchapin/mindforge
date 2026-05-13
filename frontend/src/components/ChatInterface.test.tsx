import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ChatInterface } from "@/components/ChatInterface";
import React from "react";

const mockCreateTask = vi.fn();
const mockInvalidateQueries = vi.fn();

// Mock the API module
vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual("@/lib/api");
  return {
    ...actual,
    createTask: (...args: unknown[]) => mockCreateTask(...args),
  };
});

// Mock the React Query hooks
vi.mock("@tanstack/react-query", async () => {
  const actual = await vi.importActual("@tanstack/react-query");
  return {
    ...actual,
    useMutation: vi.fn((options) => ({
      mutate: (vars: unknown) => {
        mockCreateTask(vars);
        options.onSuccess?.();
      },
      isPending: false,
    })),
    useQueryClient: vi.fn(() => ({
      invalidateQueries: mockInvalidateQueries,
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

describe("ChatInterface", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders input field and send button", () => {
    renderWithQuery(<ChatInterface />);

    expect(screen.getByPlaceholderText("What would you like to do?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("calls createTask when form is submitted", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ChatInterface />);

    const input = screen.getByPlaceholderText("What would you like to do?");
    await user.type(input, "Summarize my GitHub commits");

    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mockCreateTask).toHaveBeenCalledWith("Summarize my GitHub commits");
  });

  it("clears input after mutation success", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ChatInterface />);

    const input = screen.getByPlaceholderText("What would you like to do?");
    await user.type(input, "Test task");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(input).toHaveValue("");
    });
  });

  it("does not submit empty input", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ChatInterface />);

    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mockCreateTask).not.toHaveBeenCalled();
  });

  it("does not submit whitespace-only input", async () => {
    const user = userEvent.setup();
    renderWithQuery(<ChatInterface />);

    const input = screen.getByPlaceholderText("What would you like to do?");
    await user.type(input, "   ");
    await user.click(screen.getByRole("button", { name: "Send" }));

    expect(mockCreateTask).not.toHaveBeenCalled();
  });
});