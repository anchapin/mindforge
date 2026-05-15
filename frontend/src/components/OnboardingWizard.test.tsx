import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { OnboardingWizard } from "@/components/OnboardingWizard";

// #72 — handleComplete and handleSkip now POST to the backend. Mock both
// so the existing UI tests don't issue real network calls.
vi.mock("@/lib/api", () => ({
  submitOnboarding: vi.fn().mockResolvedValue(undefined),
  submitOnboardingSkip: vi.fn().mockResolvedValue(undefined),
}));

describe("OnboardingWizard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders step 1 with integration options", () => {
    render(<OnboardingWizard />);

    expect(screen.getByText("Connect your first tool")).toBeInTheDocument();
    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("GitHub")).toBeInTheDocument();
    expect(screen.getByText("Stripe")).toBeInTheDocument();
  });

  it("shows step indicator with 3 steps", () => {
    render(<OnboardingWizard />);

    // Should have 3 step indicators
    const stepIndicators = document.querySelectorAll(".h-2.flex-1");
    expect(stepIndicators).toHaveLength(3);
  });

  it("advances to step 2 when integration is selected and continue clicked", async () => {
    render(<OnboardingWizard />);

    // Select an integration
    await userEvent.click(screen.getByText("Email"));

    // Click continue
    await userEvent.click(screen.getByText("Continue →"));

    expect(screen.getByText("Tell us how you write")).toBeInTheDocument();
  });

  it("can navigate back from step 2 to step 1", async () => {
    render(<OnboardingWizard />);

    // Go to step 2
    await userEvent.click(screen.getByText("Email"));
    await userEvent.click(screen.getByText("Continue →"));

    // Go back
    await userEvent.click(screen.getByText("← Back"));

    expect(screen.getByText("Connect your first tool")).toBeInTheDocument();
  });

  it("advances to step 3 when writing samples are provided", async () => {
    render(<OnboardingWizard />);

    // Go to step 2
    await userEvent.click(screen.getByText("Email"));
    await userEvent.click(screen.getByText("Continue →"));

    // Fill in writing samples using exact placeholder text
    const textareas = screen.getAllByRole("textbox");
    expect(textareas).toHaveLength(3);
    for (const textarea of textareas) {
      await userEvent.type(textarea, "Sample email content");
    }

    // Click continue
    await userEvent.click(screen.getByText("Continue →"));

    expect(screen.getByText("Meet your AI team")).toBeInTheDocument();
  });

  it("renders agent cards on step 3", async () => {
    render(<OnboardingWizard />);

    // Navigate to step 3
    await userEvent.click(screen.getByText("Email"));
    await userEvent.click(screen.getByText("Continue →"));

    const textareas = screen.getAllByRole("textbox");
    for (const textarea of textareas) {
      await userEvent.type(textarea, "Sample");
    }
    await userEvent.click(screen.getByText("Continue →"));

    expect(screen.getByText("COO Agent")).toBeInTheDocument();
    expect(screen.getByText("CMO Agent")).toBeInTheDocument();
    expect(screen.getByText("Researcher Agent")).toBeInTheDocument();
    expect(screen.getByText("Engineer Agent")).toBeInTheDocument();
  });

  it("calls onComplete when 'Launch Dashboard' is clicked", async () => {
    const onComplete = vi.fn();
    render(<OnboardingWizard onComplete={onComplete} />);

    // Navigate to step 3
    await userEvent.click(screen.getByText("Email"));
    await userEvent.click(screen.getByText("Continue →"));

    const textareas = screen.getAllByRole("textbox");
    for (const textarea of textareas) {
      await userEvent.type(textarea, "Sample");
    }
    await userEvent.click(screen.getByText("Continue →"));

    // Click Launch Dashboard (async — handleComplete posts then calls onComplete)
    await userEvent.click(screen.getByText("Launch Dashboard →"));

    await waitFor(() => expect(onComplete).toHaveBeenCalled());
  });

  it("calls onSkip when 'Skip for now' is clicked", async () => {
    const onSkip = vi.fn();
    render(<OnboardingWizard onSkip={onSkip} />);

    await userEvent.click(screen.getByText("Skip for now →"));

    await waitFor(() => expect(onSkip).toHaveBeenCalled());
  });

  it("disables continue on step 1 if no integration selected", () => {
    render(<OnboardingWizard />);

    const continueButton = screen.getByText("Continue →") as HTMLButtonElement;
    expect(continueButton).toBeDisabled();
  });

  it("allows multiple integrations to be selected", async () => {
    render(<OnboardingWizard />);

    await userEvent.click(screen.getByText("Email"));
    await userEvent.click(screen.getByText("GitHub"));

    // Both should be visually selected (has different styling)
    expect(screen.getByText("Email")).toBeInTheDocument();
    expect(screen.getByText("GitHub")).toBeInTheDocument();

    // Continue should be enabled
    const continueButton = screen.getByText("Continue →") as HTMLButtonElement;
    expect(continueButton).not.toBeDisabled();
  });
});