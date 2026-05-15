import { useState, useEffect } from "react";
import type { Task } from "../lib/api";

// ---------------------------------------------------------------------------
// Color utilities
// ---------------------------------------------------------------------------

/** Deterministic color from a string (project_id) */
function colorFromHash(projectId: string | null): string {
  if (!projectId) return "text-zinc-400 border-zinc-600";
  let hash = 0;
  for (let i = 0; i < projectId.length; i++) {
    hash = projectId.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = [
    "text-blue-400 border-blue-500",
    "text-emerald-400 border-emerald-500",
    "text-amber-400 border-amber-500",
    "text-purple-400 border-purple-500",
    "text-rose-400 border-rose-500",
    "text-cyan-400 border-cyan-500",
    "text-orange-400 border-orange-500",
    "text-pink-400 border-pink-500",
  ];
  return colors[Math.abs(hash) % colors.length];
}

const STATUS_CONFIG: Record<
  Task["status"],
  { label: string; dotColor: string; textColor: string }
> = {
  pending:   { label: "Pending",         dotColor: "bg-zinc-400", textColor: "text-zinc-400" },
  running:   { label: "Running",         dotColor: "bg-blue-400 animate-pulse", textColor: "text-blue-400" },
  draft:     { label: "Awaiting Approval", dotColor: "bg-amber-400", textColor: "text-amber-400" },
  approved:  { label: "Approved",         dotColor: "bg-indigo-400", textColor: "text-indigo-400" },
  executing: { label: "Executing",        dotColor: "bg-blue-400 animate-pulse", textColor: "text-blue-400" },
  completed: { label: "Completed",        dotColor: "bg-green-400", textColor: "text-green-400" },
  failed:    { label: "Failed",           dotColor: "bg-red-400", textColor: "text-red-400" },
};

// ---------------------------------------------------------------------------
// ProjectBadge
// ---------------------------------------------------------------------------

interface ProjectBadgeProps {
  projectId: string | null;
  onProjectChange?: (projectId: string) => void;
}

export function ProjectBadge({ projectId, onProjectChange }: ProjectBadgeProps) {
  const [open, setOpen] = useState(false);
  const colorClass = colorFromHash(projectId);
  const label = projectId ?? "(global)";

  return (
    <div className="relative inline-block">
      <button
        onClick={() => onProjectChange && setOpen((o) => !o)}
        className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium transition ${colorClass} ${
          onProjectChange ? "cursor-pointer hover:opacity-80" : "cursor-default"
        }`}
      >
        {label}
        {onProjectChange && (
          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>

      {open && onProjectChange && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full z-20 mt-1 min-w-32 rounded border border-zinc-600 bg-zinc-800 py-1 shadow-lg">
            {["(global)", "acme-corp", "beta-launch", "research"].map((p) => (
              <button
                key={p}
                onClick={() => { onProjectChange(p === "(global)" ? "" : p); setOpen(false); }}
                className={`w-full px-3 py-1.5 text-left text-xs hover:bg-zinc-700 ${
                  (p === "(global)" ? "" : p) === projectId ? "text-indigo-400" : "text-zinc-300"
                }`}
              >
                {p}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// StatusBadge
// ---------------------------------------------------------------------------

interface StatusBadgeProps {
  status: Task["status"];
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.pending;
  return (
    <div className="flex items-center gap-1.5">
      <span className={`h-2 w-2 rounded-full ${config.dotColor}`} />
      <span className={`text-xs font-medium ${config.textColor}`}>{config.label}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StepProgress
// ---------------------------------------------------------------------------

interface StepProgressProps {
  currentNode: string | null;
  nodesCompleted: string[];
  totalNodes?: number;
}

export function StepProgress({ currentNode, nodesCompleted, totalNodes }: StepProgressProps) {
  const current = nodesCompleted.length + 1;
  const total = totalNodes ?? current;

  return (
    <span className="text-xs text-zinc-500">
      Step {current}/{total}
      {currentNode && (
        <span className="ml-1 text-zinc-400">→ {currentNode}</span>
      )}
    </span>
  );
}

// ---------------------------------------------------------------------------
// CountdownTimer
// ---------------------------------------------------------------------------

interface CountdownTimerProps {
  deadlineIso: string;
  onExpire?: () => void;
}

export function CountdownTimer({ deadlineIso, onExpire }: CountdownTimerProps) {
  const [label, setLabel] = useState(() => formatTimeLeft(new Date(deadlineIso)));

  useEffect(() => {
    const id = setInterval(() => {
      const next = formatTimeLeft(new Date(deadlineIso));
      setLabel(next);
      if (next === "expired") {
        clearInterval(id);
        onExpire?.();
      }
    }, 30_000);
    return () => clearInterval(id);
  }, [deadlineIso, onExpire]);

  return (
    <span className="text-xs tabular-nums text-zinc-400">{label} left</span>
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

// ---------------------------------------------------------------------------
// TaskCard
// ---------------------------------------------------------------------------

interface TaskCardProps {
  task: Task;
  onClick?: () => void;
  onProjectChange?: (taskId: string, projectId: string) => void;
}

export function TaskCard({ task, onClick, onProjectChange }: TaskCardProps) {
  const [expanded, setExpanded] = useState(false);

  const { status, project_id } = task;
  const ctx = task.context as Record<string, unknown> | undefined;
  const nodesCompleted: string[] = (Array.isArray(ctx?.nodes_completed) ? ctx.nodes_completed : []) as string[];
  const currentNode: string | null = typeof ctx?.current_node === "string" ? ctx.current_node : null;
  const approvalDeadlineIso: string | null = typeof ctx?.approval_deadline_iso === "string" ? ctx.approval_deadline_iso : null;
  const draftContent: { body?: string; subject?: string } | null = ctx?.draft_content as typeof draftContent | null ?? null;

  const isRunning = status === "running" || status === "executing";
  const isDraft = status === "draft";
  const isCompleted = status === "completed";
  const isFailed = status === "failed";

  return (
    <div
      className={`rounded border bg-zinc-800 p-4 transition ${
        isDraft ? "border-amber-600 hover:border-amber-500" : "border-zinc-700 hover:border-zinc-600"
      }`}
      onClick={onClick}
    >
      {/* Header row */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          {/* Project + Agent row */}
          <div className="flex flex-wrap items-center gap-2">
            <ProjectBadge
              projectId={project_id}
              onProjectChange={onProjectChange ? (pid) => onProjectChange(task.id, pid) : undefined}
            />
            <span className="text-xs text-zinc-500 capitalize">{task.task_type}</span>
            <span className="text-xs text-zinc-600">·</span>
            <span className="text-xs text-zinc-500">
              {task.skill_id ? task.skill_id.split("-")[0] + " skill" : "ad-hoc"}
            </span>
          </div>

          {/* Description */}
          <p className="mt-1.5 truncate text-sm font-medium text-zinc-100">{task.description}</p>

          {/* Meta row */}
          <div className="mt-1.5 flex flex-wrap items-center gap-3">
            <StatusBadge status={status} />

            {isRunning && (
              <StepProgress
                currentNode={currentNode}
                nodesCompleted={nodesCompleted}
                totalNodes={4}
              />
            )}

            {isDraft && approvalDeadlineIso && (
              <CountdownTimer deadlineIso={approvalDeadlineIso} />
            )}

            {isCompleted && (
              <span className="text-xs text-green-400">Completed ✓</span>
            )}

            {isFailed && (
              <span className="text-xs text-red-400">Failed — tap for details</span>
            )}
          </div>
        </div>

        {/* Expand chevron for draft */}
        {isDraft && (
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded((v) => !v); }}
            className="flex h-8 w-8 items-center justify-center rounded hover:bg-zinc-700"
          >
            <svg
              className={`h-4 w-4 text-zinc-400 transition ${expanded ? "rotate-180" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        )}
      </div>

      {/* Expanded DraftReview inline */}
      {expanded && isDraft && draftContent && approvalDeadlineIso && (
        <div className="mt-4 border-t border-zinc-700 pt-4">
          <DraftReviewInline
            taskId={task.id}
            draft={draftContent}
            approvalDeadlineIso={approvalDeadlineIso}
            onCollapse={() => setExpanded(false)}
          />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DraftReviewInline (minimal draft content display when expanded)
// ---------------------------------------------------------------------------

interface DraftReviewInlineProps {
  taskId: string;
  draft: { body?: string; subject?: string };
  approvalDeadlineIso: string;
  onCollapse: () => void;
}

function DraftReviewInline({ taskId, draft, approvalDeadlineIso, onCollapse }: DraftReviewInlineProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedBody, setEditedBody] = useState(draft.body ?? "");
  const [rejectFeedback, setRejectFeedback] = useState("");
  const [showReject, setShowReject] = useState(false);

  const deadline = new Date(approvalDeadlineIso);
  const timeLeft = formatTimeLeft(deadline);

  return (
    <div className="rounded border border-amber-600/50 bg-amber-900/10 p-3">
      <div className="mb-2 flex items-center justify-between">
        <h4 className="text-sm font-semibold text-amber-400">Draft Ready for Review</h4>
        <span className="text-xs text-zinc-400">{timeLeft} left</span>
      </div>

      {draft.subject && (
        <p className="mb-2 text-xs text-zinc-400">
          Subject: <span className="text-zinc-300">{draft.subject}</span>
        </p>
      )}

      {isEditing ? (
        <div className="space-y-2">
          <textarea
            value={editedBody}
            onChange={(e) => setEditedBody(e.target.value)}
            rows={5}
            className="w-full rounded border border-zinc-600 bg-zinc-800 px-3 py-2 text-sm text-zinc-100 focus:border-indigo-500 focus:outline-none"
          />
          <p className="text-xs text-amber-400">You modified this draft</p>
          <div className="flex gap-2">
            <button
              onClick={() => setIsEditing(false)}
              className="rounded border border-zinc-600 px-3 py-1 text-xs text-zinc-300"
            >
              Cancel
            </button>
            <button
              onClick={() => { alert(`Approve task ${taskId} with edited content`); setIsEditing(false); }}
              className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-500"
            >
              Approve & Send
            </button>
          </div>
        </div>
      ) : (
        <>
          <pre className="max-h-40 overflow-y-auto whitespace-pre-wrap text-xs text-zinc-300">
            {draft.body ?? ""}
          </pre>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              onClick={() => setIsEditing(true)}
              className="rounded border border-zinc-600 px-3 py-1 text-xs text-zinc-300 hover:border-zinc-500"
            >
              Edit draft before approving
            </button>
            {!showReject && (
              <button
                onClick={() => setShowReject(true)}
                className="rounded border border-red-700 px-3 py-1 text-xs text-red-400 hover:border-red-600"
              >
                Reject
              </button>
            )}
            <button
              onClick={onCollapse}
              className="rounded border border-zinc-600 px-3 py-1 text-xs text-zinc-400 hover:border-zinc-500"
            >
              Collapse
            </button>
          </div>

          {showReject && (
            <div className="mt-3 space-y-2">
              <textarea
                value={rejectFeedback}
                onChange={(e) => setRejectFeedback(e.target.value)}
                placeholder="What should change? (min 10 chars)"
                rows={2}
                className="w-full rounded border border-zinc-600 bg-zinc-800 px-3 py-2 text-xs text-zinc-100 placeholder-zinc-500 focus:border-indigo-500 focus:outline-none"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => setShowReject(false)}
                  className="rounded border border-zinc-600 px-3 py-1 text-xs text-zinc-300"
                >
                  Cancel
                </button>
                <button
                  onClick={() => { alert(`Reject task ${taskId}: ${rejectFeedback}`); setShowReject(false); }}
                  disabled={rejectFeedback.length < 10}
                  className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-500 disabled:opacity-50"
                >
                  Send feedback & rerun
                </button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}