import { useState } from "react";
import { X } from "lucide-react";

interface ClarificationModalProps {
  taskId: string;
  agentName: string;
  question: string;
  choices?: string[];
  onSubmit: (response: string) => void;
  onCancel: () => void;
}

export function ClarificationModal({
  taskId,
  agentName,
  question,
  choices = [],
  onSubmit,
  onCancel,
}: ClarificationModalProps) {
  const [freeformText, setFreeformText] = useState("");

  const handleSubmit = () => {
    if (freeformText.trim()) {
      onSubmit(freeformText.trim());
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="clarification-title"
        className="w-full max-w-lg rounded-lg border border-zinc-700 bg-zinc-900 p-6 shadow-xl"
      >
        {/* Header */}
        <div className="mb-4 flex items-center justify-between">
          <h2 id="clarification-title" className="flex items-center gap-2 text-lg font-semibold text-zinc-100">
            <span>🤖</span>
            <span>{agentName} needs your input</span>
          </h2>
          <button
            onClick={onCancel}
            aria-label="Close"
            className="rounded p-1 text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-200"
          >
            <X size={20} />
          </button>
        </div>

        {/* Question */}
        <p className="mb-4 text-zinc-300">{question}</p>

        {/* Choice buttons */}
        {choices.length > 0 && (
          <div className="mb-4 flex flex-wrap gap-2">
            {choices.map((choice) => (
              <button
                key={choice}
                onClick={() => onSubmit(choice)}
                className="rounded border border-indigo-600 bg-indigo-900/30 px-4 py-2 text-sm font-medium text-indigo-300 transition hover:bg-indigo-900/50 hover:border-indigo-500"
              >
                {choice}
              </button>
            ))}
          </div>
        )}

        {/* Free-form text input */}
        <div className="mb-4 space-y-2">
          <p className="text-sm text-zinc-500">Or tell me in your own words:</p>
          <textarea
            value={freeformText}
            onChange={(e) => setFreeformText(e.target.value)}
            placeholder="Or tell me in your own words..."
            rows={3}
            className="w-full rounded border border-zinc-700 bg-zinc-800 px-3 py-2 text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
          />
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded border border-zinc-600 px-4 py-2 text-sm text-zinc-300 transition hover:border-zinc-500"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!freeformText.trim()}
            className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:opacity-50"
          >
            Submit
          </button>
        </div>
      </div>
    </div>
  );
}