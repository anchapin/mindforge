import { QueryClientProvider } from "@tanstack/react-query";
import { useTaskStore } from "./stores/taskStore";
import { queryClient } from "./lib/api";
import { ChatInterface } from "./components/ChatInterface";
import { TaskTracker } from "./components/TaskTracker";
import { DraftReview } from "./components/DraftReview";

function Dashboard() {
  const { tasks, activeTaskId, setActiveTask, wsDisconnected } = useTaskStore();
  const activeTask = activeTaskId ? tasks.get(activeTaskId) : null;

  return (
    <div className="flex min-h-screen flex-col bg-zinc-900 text-zinc-100">
      {/* Header */}
      <header className="border-b border-zinc-800 bg-zinc-900/80 sticky top-0 z-10 backdrop-blur">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-6 py-4">
          <h1 className="text-xl font-bold tracking-tight">
            MindForge <span className="text-zinc-500 text-sm font-normal">AI Team</span>
          </h1>
          <div className="flex items-center gap-4">
            <nav className="flex gap-4 text-sm text-zinc-400">
              <a href="#tasks" className="hover:text-zinc-200 transition">Tasks</a>
              <a href="#skills" className="hover:text-zinc-200 transition">Skills</a>
            </nav>
          </div>
        </div>
      </header>

      {/* WS disconnect banner */}
      {wsDisconnected && (
        <div className="bg-amber-900/30 border-b border-amber-700 px-6 py-2 text-sm text-amber-300">
          Live updates paused -- your task state is up to date as of a few minutes ago.
        </div>
      )}

      {/* Main */}
      <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-8 space-y-8">
        {/* Chat input */}
        <section>
          <ChatInterface />
        </section>

        {/* Task tracker */}
        <section id="tasks">
          <h2 className="mb-4 text-lg font-semibold">Tasks</h2>
          <TaskTracker />
        </section>
      </main>

      {/* Task detail drawer */}
      {activeTask && (
        <div className="fixed inset-y-0 right-0 w-full max-w-lg border-l border-zinc-700 bg-zinc-900 overflow-y-auto z-20 shadow-xl">
          <div className="sticky top-0 flex items-center justify-between border-b border-zinc-700 bg-zinc-900 px-4 py-3">
            <h2 className="font-semibold">Task Detail</h2>
            <button
              onClick={() => setActiveTask(null)}
              className="rounded p-1 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200"
            >
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
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

            {activeTask.status === "draft" && activeTask.context?.draft_content && (
              <DraftReview
                taskId={activeTask.id}
                draft={activeTask.context.draft_content as { body: string; subject?: string }}
                approvalDeadlineIso={activeTask.context.approval_deadline_iso as string ?? new Date(Date.now() + 86400000).toISOString()}
              />
            )}

            {activeTask.status === "failed" && activeTask.context?.error && (
              <div className="rounded border border-red-800 bg-red-900/20 p-3 text-sm text-red-300">
                {activeTask.context.error}
              </div>
            )}

            {activeTask.completed_at && (
              <div>
                <p className="text-sm text-zinc-400">Completed at</p>
                <p className="mt-1 text-sm">{new Date(activeTask.completed_at).toLocaleString()}</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  );
}
