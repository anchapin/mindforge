import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { getGlobalWS, type WSMessage } from "../lib/websocket";
import { useTaskStore } from "../stores/taskStore";

export function WSMessageHandler() {
  const queryClient = useQueryClient();
  const { upsertTask, setWsDisconnected, updateTaskStatus } = useTaskStore();

  useEffect(() => {
    const ws = getGlobalWS();

    const handler = async (msg: WSMessage) => {
      switch (msg.type) {
        case "task_created":
        case "task_status_update":
        case "task_completed":
        case "task_failed":
          queryClient.invalidateQueries({ queryKey: ["tasks"] });
          break;

        case "draft_ready":
          queryClient.invalidateQueries({ queryKey: ["tasks"] });
          break;

        case "approval_resolved":
          if (msg.task_id && msg.action === "approved") {
            updateTaskStatus(msg.task_id as string, "executing");
          }
          break;

        case "stream_token":
          // Streaming token display -- handled by task detail
          break;
      }
    };

    const unsubscribe = ws.subscribe(handler);
    return unsubscribe;
  }, [queryClient, upsertTask, setWsDisconnected, updateTaskStatus]);

  return null;
}
