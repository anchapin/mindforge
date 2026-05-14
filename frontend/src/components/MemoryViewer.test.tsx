import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { MemoryViewer } from "@/components/MemoryViewer";
import React from "react";

// Helper to create a query client with empty default values
function createTestQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function TestWrapper({ children }: { children: React.ReactNode }) {
  return (
    <QueryClientProvider client={createTestQueryClient()}>
      {children}
    </QueryClientProvider>
  );
}

// Mock API module
vi.mock("@/lib/api", async () => {
  return {
    listMemory: vi.fn(),
    searchMemory: vi.fn(),
  };
});

// Mock React Query - use vi.hoisted to ensure proper initialization
const mockUseQuery = vi.hoisted(() => vi.fn());

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    useQuery: mockUseQuery,
  };
});

describe("MemoryViewer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders tab buttons for memory types", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.listMemory).mockResolvedValue({ semantic: [], episodic: [], style: [] });
    mockUseQuery.mockReturnValue({
      data: { semantic: [], episodic: [], style: [] },
      isLoading: false,
    });

    render(<TestWrapper><MemoryViewer /></TestWrapper>);

    expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Semantic" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Episodes" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Writing Style" })).toBeInTheDocument();
  });

  it("renders semantic memory entries", async () => {
    const api = await import("@/lib/api");
    const memories = {
      semantic: [
        { id: "sem-1", memory_type: "semantic", content: "User prefers concise responses", created_at: "2024-01-01T00:00:00Z" },
      ],
      episodic: [],
      style: [],
    };
    vi.mocked(api.listMemory).mockResolvedValue(memories);
    mockUseQuery.mockReturnValue({ data: memories, isLoading: false });

    render(<TestWrapper><MemoryViewer /></TestWrapper>);

    await waitFor(() => {
      expect(screen.getByText(/User prefers concise responses/)).toBeInTheDocument();
    });
  });

  it("renders search input", async () => {
    mockUseQuery.mockReturnValue({
      data: { semantic: [], episodic: [], style: [] },
      isLoading: false,
    });

    render(<TestWrapper><MemoryViewer /></TestWrapper>);

    expect(screen.getByPlaceholderText("Search memories...")).toBeInTheDocument();
  });

  it("toggles memory injection when checkbox is toggled", async () => {
    mockUseQuery.mockReturnValue({
      data: { semantic: [], episodic: [], style: [] },
      isLoading: false,
    });

    render(<TestWrapper><MemoryViewer /></TestWrapper>);

    const toggle = screen.getByRole("checkbox");
    expect(toggle).not.toBeChecked();

    await userEvent.click(toggle);
    expect(toggle).toBeChecked();
  });

  it("shows empty state when no memories exist", async () => {
    mockUseQuery.mockReturnValue({
      data: { semantic: [], episodic: [], style: [] },
      isLoading: false,
    });

    render(<TestWrapper><MemoryViewer /></TestWrapper>);

    await waitFor(() => {
      expect(screen.getByText(/no memories found/i)).toBeInTheDocument();
    });
  });
});