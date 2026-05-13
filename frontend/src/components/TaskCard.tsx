import type { Task } from "../lib/api";

const STATUS_COLORS: Record<string, string> = {
  pending: "text-zinc-400",
  running: "text-blue-400",
  draft: "text-amber-400",
  approved: "text-indigo-400",
  executing: "text-blue-400",
  completed: "text-green-400",
  failed: "text-red-400",
};

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  running: "Running",
  draft: "Awaiting Approval",
  approved: "Approved",
  executing: "Executing",
  completed: "Completed",
  failed: "Failed",
};

interface TaskCardProps {
  task: Task;
  onClick?: () => void;
}

export function TaskCard({ task, onClick }: TaskCardProps) {
  const statusColor = STATUS_COLORS[task.status] ?? "text-zinc-400";
  const statusLabel = STATUS_LABELS[task.status] ?? task.status;
  const timeAgo = formatTimeAgo(new Date(task.created_at));

  return (
    <div
      onClick={onClick}
      className="cursor-pointer rounded border border-zinc-700 bg-zinc-800 p-4 transition hover:border-zinc-600"
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-zinc-100">{task.description}</p>
          <p className="mt-1 text-sm text-zinc-500">
            {task.task_type} &middot; {timeAgo}
          </p>
        </div>
        <span className={`ml-2 shrink-0 text-sm font-medium ${statusColor}`}>
          {statusLabel}
        </span>
      </div>
      {task.project_id && (
        <span className="mt-2 inline-block rounded bg-zinc-700 px-2 py-0.5 text-xs text-zinc-400">
          {task.project_id}
        </span>
      )}
    </div>
  );
}

function formatTimeAgo(date: Date): string {
  const diff = Date.now() - date.getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
