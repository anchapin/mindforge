import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getGlobalWS, type WSMessage } from "../lib/websocket";
import { useTaskStore } from "../stores/taskStore";
import { useNotificationStore } from "../stores/notificationStore";

/**
 * Translates incoming WS frames into:
 *   - taskStore mutations (existing behavior)
 *   - notificationStore pushes for user-facing events (#47):
 *       draft_ready, task_failed, approval_resolved, clarification_request
 *
 * The notification queue is bounded inside the store; this handler stays
 * dumb (no de-dup logic here).
 */
export function WSMessageHandler() {
  const queryClient = useQueryClient();
  const { upsertTask, setWsDisconnected, updateTaskStatus } = useTaskStore();
  const pushNotification = useNotificationStore((s) => s.pushNotification);
  const pushClarification = useNotificationStore((s) => s.pushClarification);

  useEffect(() => {
    const ws = getGlobalWS();

    const handler = async (msg: WSMessage) => {
      switch (msg.type) {
        case "task_created":
        case "task_status_update":
        case "task_completed":
          queryClient.invalidateQueries({ queryKey: ["tasks"] });
          if (msg.type === "task_completed" && msg.task_id) {
            pushNotification({
              id: `task-completed-${msg.task_id}`,
              type: "success",
              message: `Task ${String(msg.task_id).slice(0, 8)} completed`,
              timestamp: new Date().toISOString(),
            });
          }
          break;

        case "task_failed":
          queryClient.invalidateQueries({ queryKey: ["tasks"] });
          if (msg.task_id) {
            pushNotification({
              id: `task-failed-${msg.task_id}`,
              type: "error",
              message: `Task ${String(msg.task_id).slice(0, 8)} failed${
                msg.error ? `: ${String(msg.error)}` : ""
              }`,
              timestamp: new Date().toISOString(),
            });
          }
          break;

        case "draft_ready":
          queryClient.invalidateQueries({ queryKey: ["tasks"] });
          if (msg.task_id) {
            pushNotification({
              id: `draft-ready-${msg.task_id}`,
              type: "warning",  // warning = needs user attention
              message: `Draft ready for review (task ${String(msg.task_id).slice(0, 8)})`,
              timestamp: new Date().toISOString(),
            });
          }
          break;

        case "approval_resolved":
          if (msg.task_id && msg.action === "approved") {
            updateTaskStatus(msg.task_id as string, "executing");
          }
          break;

        case "clarification_request":
          if (msg.task_id) {
            pushClarification({
              taskId: String(msg.task_id),
              agentName: String(msg.agent_role ?? msg.agent_name ?? "agent"),
              question: String(msg.question ?? "Please clarify how I should proceed."),
              choices: Array.isArray(msg.options)
                ? (msg.options as unknown[]).map(String)
                : [],
              deadlineIso: msg.deadline_iso ? String(msg.deadline_iso) : undefined,
            });
            pushNotification({
              id: `clarification-${msg.task_id}`,
              type: "info",
              message: `Clarification needed (task ${String(msg.task_id).slice(0, 8)})`,
              timestamp: new Date().toISOString(),
            });
          }
          break;

        case "stream_token":
          // Streaming token display -- handled by task detail
          break;
      }
    };

    const unsubscribe = ws.subscribe(handler);
    return unsubscribe;
  }, [
    queryClient,
    upsertTask,
    setWsDisconnected,
    updateTaskStatus,
    pushNotification,
    pushClarification,
  ]);

  return null;
}
