/**
 * /tasks — the dashboard. Chat input + task list + draft-review drawer.
 *
 * Lifted from the previous App.tsx body in #48; behavior unchanged except
 * that this is now a route component instead of the only page.
 */

import { useTaskStore } from "../stores/taskStore";
import { ChatInterface } from "../components/ChatInterface";
import { TaskTracker } from "../components/TaskTracker";
import { DraftReview } from "../components/DraftReview";

export default function TasksPage() {
  const { tasks, activeTaskId, setActiveTask } = useTaskStore();
  const activeTask = activeTaskId ? tasks.get(activeTaskId) : null;

  return (
    <>
      <section>
        <ChatInterface />
      </section>

      <section id="tasks">
        <h2 className="mb-4 text-lg font-semibold">Tasks</h2>
        <TaskTracker />
      </section>

      {/* Task detail drawer */}
      {activeTask && (
        <div className="fixed inset-y-0 right-0 w-full max-w-lg border-l border-zinc-700 bg-zinc-900 overflow-y-auto z-20 shadow-xl">
          <div className="sticky top-0 flex items-center justify-between border-b border-zinc-700 bg-zinc-900 px-4 py-3">
            <h2 className="font-semibold">Task Detail</h2>
            <button
              onClick={() => setActiveTask(null)}
              aria-label="Close task detail"
              className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            >
              <svg
                className="h-5 w-5"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
          <div className="p-4 space-y-4">
            <div>
              <p className="text-sm text-zinc-400">Description</p>
              <p className="mt-1 font-medium">{activeTask.description}</p>
            </div>
            <div>
              <p className="text-sm text-zinc-400">Status</p>
              <p className="mt-1 font-medium capitalize">{activeTask.status}</p>
            </div>
            <div>
              <p className="text-sm text-zinc-400">Type</p>
              <p className="mt-1 font-medium">{activeTask.task_type}</p>
            </div>

            {activeTask.status === "draft" && activeTask.context?.draft_content ? (
              <DraftReview
                taskId={activeTask.id}
                draft={
                  activeTask.context.draft_content as {
                    body: string;
                    subject?: string;
                  }
                }
                approvalDeadlineIso={
                  (activeTask.context.approval_deadline_iso as string) ??
                  new Date(Date.now() + 86400000).toISOString()
                }
              />
            ) : null}

            {activeTask.status === "failed" && activeTask.context?.error ? (
              <div className="rounded border border-red-800 bg-red-900/20 p-3 text-sm text-red-300">
                {String(activeTask.context.error)}
              </div>
            ) : null}

            {activeTask.completed_at && (
              <div>
                <p className="text-sm text-zinc-400">Completed at</p>
                <p className="mt-1 text-sm">
                  {new Date(activeTask.completed_at).toLocaleString()}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
