import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTaskStore } from "../stores/taskStore";
import { approveTask, rejectTask, type DraftContent } from "../lib/api";

interface DraftReviewProps {
  taskId: string;
  draft: DraftContent;
  approvalDeadlineIso: string;
}

export function DraftReview({ taskId, draft, approvalDeadlineIso }: DraftReviewProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedBody, setEditedBody] = useState(draft.body ?? "");
  const [editedSubject] = useState(draft.subject ?? "");
  const [rejectFeedback, setRejectFeedback] = useState("");
  const [showReject, setShowReject] = useState(false);
  const { updateTaskStatus } = useTaskStore();

  const approveMutation = useMutation({
    mutationFn: (content?: DraftContent) => approveTask(taskId, content),
    onSuccess: () => updateTaskStatus(taskId, "approved"),
  });

  const rejectMutation = useMutation({
    mutationFn: (feedback: string) => rejectTask(taskId, feedback),
    onSuccess: () => updateTaskStatus(taskId, "failed"),
  });

  const deadline = new Date(approvalDeadlineIso);
  const timeLeft = formatTimeLeft(deadline);

  return (
    <div className="rounded border border-amber-600 bg-amber-900/20 p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="font-semibold text-amber-400">Draft Ready for Review</h3>
        <span className="text-sm text-zinc-400">{timeLeft} left</span>
      </div>

      {draft.subject && (
        <p className="mb-2 text-sm font-medium text-zinc-300">
          Subject: {draft.subject}
        </p>
      )}

      {isEditing ? (
        <div className="space-y-2">
          <textarea
            value={editedBody}
            onChange={(e) => setEditedBody(e.target.value)}
            rows={6}
            className="w-full rounded border border-zinc-600 bg-zinc-800 px-3 py-2 text-zinc-100 focus:border-indigo-500 focus:outline-none"
          />
          <p className="text-xs text-amber-400">You modified this draft</p>
        </div>
      ) : (
        <pre className="whitespace-pre-wrap text-sm text-zinc-300">{draft.body}</pre>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {!isEditing && !showReject && (
          <button
            onClick={() => setIsEditing(true)}
            className="rounded border border-zinc-600 px-3 py-1.5 text-sm text-zinc-300 transition hover:border-zinc-500"
          >
            Edit draft before approving
          </button>
        )}

        {isEditing && (
          <>
            <button
              onClick={() => setIsEditing(false)}
              className="rounded border border-zinc-600 px-3 py-1.5 text-sm text-zinc-300"
            >
              Cancel
            </button>
            <button
              onClick={() =>
                approveMutation.mutate({
                  ...draft,
                  body: editedBody,
                  subject: editedSubject,
                } as DraftContent)
              }
              disabled={approveMutation.isPending}
              className="rounded bg-green-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-green-500 disabled:opacity-50"
            >
              {approveMutation.isPending ? "Approving..." : "Approve & Send"}
            </button>
          </>
        )}

        {!isEditing && !showReject && (
          <button
            onClick={() => setShowReject(true)}
            className="rounded border border-red-700 px-3 py-1.5 text-sm text-red-400 transition hover:border-red-600"
          >
            Reject
          </button>
        )}

        {showReject && (
          <div className="w-full space-y-2">
            <textarea
              value={rejectFeedback}
              onChange={(e) => setRejectFeedback(e.target.value)}
              placeholder="What should change?"
              rows={3}
              minLength={10}
              className="w-full rounded border border-zinc-600 bg-zinc-800 px-3 py-2 text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
            />
            <div className="flex gap-2">
              <button
                onClick={() => setShowReject(false)}
                className="rounded border border-zinc-600 px-3 py-1.5 text-sm text-zinc-300"
              >
                Cancel
              </button>
              <button
                onClick={() => rejectMutation.mutate(rejectFeedback)}
                disabled={rejectFeedback.length < 10 || rejectMutation.isPending}
                className="rounded bg-red-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
              >
                {rejectMutation.isPending ? "Sending..." : "Send feedback & rerun"}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function formatTimeLeft(deadline: Date): string {
  const diff = deadline.getTime() - Date.now();
  if (diff <= 0) return "expired";
  const hours = Math.floor(diff / 3_600_000);
  const mins = Math.floor((diff % 3_600_000) / 60_000);
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
}
