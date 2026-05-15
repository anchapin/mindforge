import { useState } from "react";

interface OnboardingWizardProps {
  onComplete?: () => void;
  onSkip?: () => void;
}

interface IntegrationOption {
  id: string;
  name: string;
  icon: string;
  description: string;
}

const INTEGRATIONS: IntegrationOption[] = [
  { id: "email", name: "Email", icon: "📧", description: "IMAP/SMTP for email" },
  { id: "github", name: "GitHub", icon: "💻", description: "API token for GitHub" },
  { id: "stripe", name: "Stripe", icon: "💳", description: "Read-only Stripe" },
];

const WRITING_EXAMPLES = [
  "Paste an example email you've sent...",
  "Another example of your writing style...",
  "One more example...",
];

export function OnboardingWizard({ onComplete, onSkip }: OnboardingWizardProps) {
  const [step, setStep] = useState(1);
  const [selectedIntegrations, setSelectedIntegrations] = useState<string[]>([]);
  const [writingSamples, setWritingSamples] = useState<string[]>(["", "", ""]);

  const handleIntegrationToggle = (id: string) => {
    setSelectedIntegrations((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id]
    );
  };

  const handleWritingSampleChange = (index: number, value: string) => {
    const updated = [...writingSamples];
    updated[index] = value;
    setWritingSamples(updated);
  };

  const handleComplete = () => {
    // The first-run gate (#46) calls onComplete to dismiss the wizard.
    // Full onboarding POST (writing samples -> writing_profile, integration
    // tokens -> integration table) happens in a follow-up that adds the
    // token inputs the current step UI doesn't yet collect. The API
    // endpoint exists at POST /api/onboarding (see backend issue #34) and
    // a typed wrapper at frontend/src/lib/api.ts (submitOnboarding).
    onComplete?.();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-lg rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl">
        {/* Header */}
        <div className="mb-6 flex items-center justify-between">
          <h1 className="text-xl font-semibold text-zinc-100">MindForge Setup</h1>
          {onSkip && (
            <button
              onClick={onSkip}
              className="text-sm text-zinc-500 hover:text-zinc-300"
            >
              Skip for now →
            </button>
          )}
        </div>

        {/* Step indicator */}
        <div className="mb-6 flex gap-2">
          {[1, 2, 3].map((s) => (
            <div
              key={s}
              className={`h-2 flex-1 rounded-full ${
                s <= step ? "bg-indigo-600" : "bg-zinc-700"
              }`}
            />
          ))}
        </div>

        {/* Step 1: Connect integrations */}
        {step === 1 && (
          <div>
            <h2 className="mb-4 text-lg font-medium text-zinc-200">
              Connect your first tool
            </h2>
            <div className="mb-4 grid gap-3">
              {INTEGRATIONS.map((integration) => (
                <button
                  key={integration.id}
                  onClick={() => handleIntegrationToggle(integration.id)}
                  className={`flex items-center gap-3 rounded border p-4 text-left transition ${
                    selectedIntegrations.includes(integration.id)
                      ? "border-indigo-600 bg-indigo-900/30"
                      : "border-zinc-700 bg-zinc-800 hover:border-zinc-600"
                  }`}
                >
                  <span className="text-2xl">{integration.icon}</span>
                  <div>
                    <p className="font-medium text-zinc-200">{integration.name}</p>
                    <p className="text-sm text-zinc-500">{integration.description}</p>
                  </div>
                </button>
              ))}
            </div>
            <button
              onClick={() => setStep(2)}
              disabled={selectedIntegrations.length === 0}
              className="w-full rounded bg-indigo-600 py-2 font-medium text-white transition hover:bg-indigo-500 disabled:opacity-50"
            >
              Continue →
            </button>
          </div>
        )}

        {/* Step 2: Writing style */}
        {step === 2 && (
          <div>
            <h2 className="mb-4 text-lg font-medium text-zinc-200">
              Tell us how you write
            </h2>
            <p className="mb-4 text-sm text-zinc-500">
              Paste 3 example emails to help us learn your style.
            </p>
            <div className="mb-4 space-y-3">
              {WRITING_EXAMPLES.map((placeholder, index) => (
                <textarea
                  key={index}
                  value={writingSamples[index]}
                  onChange={(e) => handleWritingSampleChange(index, e.target.value)}
                  placeholder={placeholder}
                  rows={3}
                  className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
                />
              ))}
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setStep(1)}
                className="flex-1 rounded border border-zinc-700 py-2 text-zinc-400 transition hover:border-zinc-600"
              >
                ← Back
              </button>
              <button
                onClick={() => setStep(3)}
                disabled={writingSamples.every((s) => s.trim().length === 0)}
                className="flex-1 rounded bg-indigo-600 py-2 font-medium text-white transition hover:bg-indigo-500 disabled:opacity-50"
              >
                Continue →
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Meet the team */}
        {step === 3 && (
          <div>
            <h2 className="mb-4 text-lg font-medium text-zinc-200">
              Meet your AI team
            </h2>
            <div className="mb-6 grid gap-4">
              {[
                { name: "COO Agent", desc: "Planner and overseer — coordinates projects and progress" },
                { name: "CMO Agent", desc: "Marketing and content — drafts emails, campaigns, social" },
                { name: "Researcher Agent", desc: "Data and web research — competitive intel and analysis" },
                { name: "Engineer Agent", desc: "Code and GitHub — reviews PRs and automates devops" },
              ].map((agent) => (
                <div
                  key={agent.name}
                  className="rounded border border-zinc-700 bg-zinc-800 p-4"
                >
                  <p className="font-medium text-zinc-200">{agent.name}</p>
                  <p className="text-sm text-zinc-500">{agent.desc}</p>
                </div>
              ))}
            </div>
            <p className="mb-4 text-center text-sm text-zinc-500">
              Your job is the chairman. They do the work. You review and approve.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setStep(2)}
                className="flex-1 rounded border border-zinc-700 py-2 text-zinc-400 transition hover:border-zinc-600"
              >
                ← Back
              </button>
              <button
                onClick={handleComplete}
                className="flex-1 rounded bg-indigo-600 py-2 font-medium text-white transition hover:bg-indigo-500"
              >
                Launch Dashboard →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}