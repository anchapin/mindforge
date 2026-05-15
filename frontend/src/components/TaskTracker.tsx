import { useQuery } from "@tanstack/react-query";
import { listTasks } from "../lib/api";
import { useTaskStore } from "../stores/taskStore";
import { TaskCard } from "./TaskCard";
import { SystemActivity } from "./SystemActivity";

export function TaskTracker() {
  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ["tasks"],
    queryFn: () => listTasks(),
    refetchInterval: 10_000,
  });

  const { setTasks: _setTasks, setActiveTask } = useTaskStore();

  const grouped = {
    running: tasks.filter((t) => ["running", "executing"].includes(t.status)),
    draft: tasks.filter((t) => t.status === "draft"),
    pending: tasks.filter((t) => t.status === "pending"),
    completed: tasks.filter((t) => t.status === "completed"),
    failed: tasks.filter((t) => t.status === "failed"),
  };

  return (
    <div className="space-y-6">

      {isLoading && <p className="text-zinc-500">Loading tasks...</p>}

      {grouped.running.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-blue-400 uppercase tracking-wide">Active</h2>
          <div className="space-y-2">
            {grouped.running.map((t) => (
              <TaskCard key={t.id} task={t} onClick={() => setActiveTask(t.id)} />
            ))}
          </div>
        </section>
      )}

      {grouped.draft.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-amber-400 uppercase tracking-wide">Awaiting Approval</h2>
          <div className="space-y-2">
            {grouped.draft.map((t) => (
              <TaskCard key={t.id} task={t} onClick={() => setActiveTask(t.id)} />
            ))}
          </div>
        </section>
      )}

      {grouped.failed.length > 0 && (
        <section>
          <h2 className="mb-2 text-sm font-semibold text-red-400 uppercase tracking-wide">Failed</h2>
          <div className="space-y-2">
            {grouped.failed.map((t) => (
              <TaskCard key={t.id} task={t} onClick={() => setActiveTask(t.id)} />
            ))}
          </div>
        </section>
      )}

      {tasks.length === 0 && !isLoading && (
        <p className="text-center text-zinc-500">
          No tasks yet. Try: &quot;Summarize my GitHub commits from the last 24 hours&quot;
        </p>
      )}

      {/* System Activity — proactive events per SPEC.md §2.7.4 */}
      <SystemActivity />
    </div>
  );
}
