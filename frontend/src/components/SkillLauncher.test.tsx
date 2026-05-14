import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { SkillLauncher } from "@/components/SkillLauncher";
import React from "react";

// Helper to create a query client
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
    listSkills: vi.fn(),
  };
});

// Mock React Query - use vi.hoisted for proper initialization
const mockUseQuery = vi.hoisted(() => vi.fn());

vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    useQuery: mockUseQuery,
  };
});

const mockSkills = [
  { id: "skill-1", name: "GitHub Daily Summary", description: "Summarize GitHub commits", version: "1.0", trigger: "github", created_at: "2024-01-01T00:00:00Z" },
  { id: "skill-2", name: "Email Follow-up", description: "Follow up on unreplied emails", version: "1.0", trigger: "email", created_at: "2024-01-02T00:00:00Z" },
];

describe("SkillLauncher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders skills heading", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.listSkills).mockResolvedValue(mockSkills);
    mockUseQuery.mockReturnValue({ data: mockSkills, isLoading: false });

    render(<TestWrapper><SkillLauncher /></TestWrapper>);

    expect(screen.getByText("Skills")).toBeInTheDocument();
  });

  it("renders skills list", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.listSkills).mockResolvedValue(mockSkills);
    mockUseQuery.mockReturnValue({ data: mockSkills, isLoading: false });

    render(<TestWrapper><SkillLauncher /></TestWrapper>);

    expect(screen.getByText("GitHub Daily Summary")).toBeInTheDocument();
    expect(screen.getByText("Email Follow-up")).toBeInTheDocument();
  });

  it("renders search input", async () => {
    mockUseQuery.mockReturnValue({ data: mockSkills, isLoading: false });

    render(<TestWrapper><SkillLauncher /></TestWrapper>);

    expect(screen.getByPlaceholderText("Search skills...")).toBeInTheDocument();
  });

  it("filters skills by search query", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.listSkills).mockResolvedValue(mockSkills);
    mockUseQuery.mockReturnValue({ data: mockSkills, isLoading: false });

    render(<TestWrapper><SkillLauncher /></TestWrapper>);

    await userEvent.type(screen.getByPlaceholderText("Search skills..."), "GitHub");

    expect(screen.getByText("GitHub Daily Summary")).toBeInTheDocument();
    expect(screen.queryByText("Email Follow-up")).not.toBeInTheDocument();
  });

  it("shows activate button for each skill", async () => {
    mockUseQuery.mockReturnValue({ data: mockSkills, isLoading: false });

    render(<TestWrapper><SkillLauncher /></TestWrapper>);

    const activateButtons = screen.getAllByRole("button", { name: "Activate" });
    expect(activateButtons).toHaveLength(2);
  });

  it("calls onActivate when skill is activated", async () => {
    const onActivate = vi.fn();
    mockUseQuery.mockReturnValue({ data: mockSkills, isLoading: false });

    render(<TestWrapper><SkillLauncher onActivate={onActivate} /></TestWrapper>);

    await userEvent.click(screen.getAllByRole("button", { name: "Activate" })[0]);

    expect(onActivate).toHaveBeenCalledWith("skill-1");
  });

  it("shows loading state", async () => {
    mockUseQuery.mockReturnValue({ data: undefined, isLoading: true });

    render(<TestWrapper><SkillLauncher /></TestWrapper>);

    expect(screen.getByText("Loading skills...")).toBeInTheDocument();
  });

  it("shows empty state when no skills", async () => {
    mockUseQuery.mockReturnValue({ data: [], isLoading: false });

    render(<TestWrapper><SkillLauncher /></TestWrapper>);

    expect(screen.getByText("No skills found")).toBeInTheDocument();
  });
});