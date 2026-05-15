/**
 * /tasks/:taskId/debug — TaskDebug host.
 */

import { useParams } from "@tanstack/react-router";
import { TaskDebug } from "../components/TaskDebug";

export default function TaskDebugPage() {
  const params = useParams({ strict: false }) as { taskId?: string };
  if (!params.taskId) {
    return <p className="text-sm text-red-400">Missing task id in URL.</p>;
  }
  return <TaskDebug taskId={params.taskId} />;
}
