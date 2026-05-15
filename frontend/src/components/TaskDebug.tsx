/**
 * TaskDebug — node-by-node walk through a task's skill execution (#49).
 *
 * Reads task.context.skill_execution_context which the executor persists
 * after every node. Renders an ordered list with each completed node's
 * scratch output, status, and any captured error.
 *
 * Doesn't show LLM prompts (the executor doesn't currently persist
 * them); a follow-up could add prompt logging behind a flag.
 */

import { useQuery } from "@tanstack/react-query";
import { getTask, type Task } from "../lib/api";

interface TaskDebugProps {
  taskId: string;
}

interface ScratchEntry {
  status?: string;
  output?: { text?: string; tools_offered?: string[]; tools_used?: string[] };
  error?: string;
}

interface SkillExecutionContext {
  skill_id?: string;
  skill_version?: number;
  node_id?: string;
  nodes_completed?: string[];
  scratch?: Record<string, ScratchEntry>;
}

export function TaskDebug({ taskId }: TaskDebugProps) {
  const { data, isLoading, error } = useQuery<Task>({
    queryKey: ["task", taskId],
    queryFn: () => getTask(taskId),
    refetchInterval: 5_000,  // refresh while task is running
  });

  if (isLoading) {
    return <p className="text-sm text-zinc-500">Loading task…</p>;
  }
  if (error || !data) {
    return (
      <p className="text-sm text-red-400">
        Could not load task {taskId}: {error instanceof Error ? error.message : "unknown error"}
      </p>
    );
  }

  const ctx = data.context as { skill_execution_context?: SkillExecutionContext };
  const exec = ctx.skill_execution_context;

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">Task {taskId.slice(0, 8)}</h2>
        <p className="text-sm text-zinc-400">{data.description}</p>
        <div className="flex gap-3 text-xs">
          <Badge label="Status" value={data.status} />
          {exec?.skill_id && <Badge label="Skill" value={exec.skill_id} />}
          {exec?.node_id && <Badge label="Current node" value={exec.node_id} />}
        </div>
      </header>

      {!exec ? (
        <p className="text-sm text-zinc-500">
          This task didn't run as a skill (no execution context to walk).
        </p>
      ) : (
        <NodeWalk exec={exec} />
      )}
    </div>
  );
}

function Badge({ label, value }: { label: string; value: string }) {
  return (
    <span className="rounded bg-zinc-800 px-2 py-0.5 text-zinc-300">
      <span className="text-zinc-500">{label}:</span> {value}
    </span>
  );
}

function NodeWalk({ exec }: { exec: SkillExecutionContext }) {
  const completed = exec.nodes_completed ?? [];
  const scratch = exec.scratch ?? {};

  if (completed.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No nodes have completed yet. Refresh in a few seconds.
      </p>
    );
  }

  return (
    <ol className="space-y-3 border-l border-zinc-700 pl-4">
      {completed.map((nodeId, idx) => {
        const entry = scratch[nodeId];
        const status = entry?.status ?? "unknown";
        const isFailure = status === "failure";
        const isSuccess = status === "success";
        return (
          <li key={`${nodeId}-${idx}`} className="space-y-1">
            <div className="flex items-center gap-2">
              <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs font-mono text-zinc-300">
                {idx + 1}. {nodeId}
              </span>
              <span
                className={
                  "rounded px-2 py-0.5 text-xs " +
                  (isSuccess
                    ? "bg-green-900/40 text-green-300"
                    : isFailure
                      ? "bg-red-900/40 text-red-300"
                      : "bg-zinc-800 text-zinc-400")
                }
              >
                {status}
              </span>
            </div>
            {entry?.output?.text && (
              <pre className="whitespace-pre-wrap rounded bg-zinc-950 p-2 text-xs text-zinc-200">
                {entry.output.text}
              </pre>
            )}
            {entry?.output?.tools_offered && entry.output.tools_offered.length > 0 && (
              <p className="text-xs text-zinc-500">
                Tools offered: {entry.output.tools_offered.join(", ")}
              </p>
            )}
            {entry?.error && (
              <p className="rounded border border-red-800 bg-red-900/20 p-2 text-xs text-red-300">
                {entry.error}
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
