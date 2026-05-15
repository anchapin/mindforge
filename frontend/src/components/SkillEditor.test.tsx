/**
 * SkillEditor (#49) — covers debounced validation, save gating, and
 * DAG preview rendering against mocked /api/skills/validate responses.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SkillEditor } from "./SkillEditor";

// Module-level state so we can flip the next mocked validation response per-test
let nextValidation: any = {
  valid: true,
  errors: [],
  graph: {
    nodes: [
      { id: "a", agent: "researcher" },
      { id: "b", agent: "cmo", requires_approval: true },
    ],
    edges: [{ from: "a", to: "b" }],
  },
};

vi.mock("@/lib/api", () => ({
  validateSkillYaml: vi.fn(async () => nextValidation),
}));

describe("SkillEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    nextValidation = {
      valid: true,
      errors: [],
      graph: {
        nodes: [{ id: "a", agent: "researcher" }],
        edges: [],
      },
    };
  });

  it("renders the YAML textarea with the default skill template", () => {
    render(<SkillEditor />);
    const textarea = screen.getByLabelText("Skill YAML") as HTMLTextAreaElement;
    expect(textarea).toBeInTheDocument();
    // Default template includes "name: my-new-skill"
    expect(textarea.value).toMatch(/my-new-skill/);
  });

  it("uses initialYaml when provided", () => {
    render(<SkillEditor initialYaml={"name: custom\n"} />);
    const textarea = screen.getByLabelText("Skill YAML") as HTMLTextAreaElement;
    expect(textarea.value).toBe("name: custom\n");
  });

  it("shows the Valid badge after debounced validation succeeds", async () => {
    render(<SkillEditor />);
    await waitFor(() => {
      expect(screen.getByText(/Valid/i)).toBeInTheDocument();
    });
  });

  it("shows error count badge AND error list when validation fails", async () => {
    nextValidation = {
      valid: false,
      errors: ["Cycle detected via edge b -> a", "Self-loop on c"],
      graph: { nodes: [{ id: "a" }, { id: "b" }, { id: "c" }], edges: [] },
    };
    render(<SkillEditor />);
    await waitFor(() => {
      expect(screen.getByText(/2 errors/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Cycle detected/)).toBeInTheDocument();
    expect(screen.getByText(/Self-loop on c/)).toBeInTheDocument();
  });

  it("disables Save while invalid and enables it after validation succeeds", async () => {
    nextValidation = {
      valid: false,
      errors: ["Empty graph"],
      graph: null,
    };
    const onSave = vi.fn();
    render(<SkillEditor onSave={onSave} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Save skill/i })).toBeDisabled();
    });

    // Flip to valid; type one char to retrigger debounce
    nextValidation = {
      valid: true,
      errors: [],
      graph: { nodes: [{ id: "a" }], edges: [] },
    };
    const textarea = screen.getByLabelText("Skill YAML");
    await userEvent.type(textarea, " ");

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Save skill/i })).not.toBeDisabled();
    });
  });

  it("calls onSave when Save is clicked while valid", async () => {
    const onSave = vi.fn(async () => {});
    render(<SkillEditor onSave={onSave} />);

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Save skill/i })).not.toBeDisabled();
    });
    await userEvent.click(screen.getByRole("button", { name: /Save skill/i }));
    await waitFor(() => expect(onSave).toHaveBeenCalled());
  });

  it("renders the DAG preview once the graph payload arrives", async () => {
    render(<SkillEditor />);
    await waitFor(() => {
      const svg = screen.getByRole("img", { name: /Skill execution graph preview/i });
      expect(svg).toBeInTheDocument();
    });
  });
});
