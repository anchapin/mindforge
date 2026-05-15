export type WSMessageType =
  | "task_created"
  | "task_status_update"
  | "draft_ready"
  | "approval_resolved"
  | "clarification_request"
  | "agent_message"
  | "task_completed"
  | "task_failed"
  | "skill_triggered"
  | "stream_token"
  | "sync"
  // Proactive events (Phase 3)
  | "billing_anomaly_detected"
  | "calendar_conflict_detected"
  | "follow_up_draft_created"
  | "worker_status_changed";

export interface WSMessage {
  type: WSMessageType;
  task_id?: string;
  [key: string]: unknown;
}

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

type MessageHandler = (msg: WSMessage) => void;

export class WSClient {
  private ws: WebSocket | null = null;
  private handlers: Set<MessageHandler> = new Set();
  private reconnectAttempts = 0;
  private maxReconnects = 5;
  private taskId: string | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(taskId?: string) {
    this.taskId = taskId ?? null;
  }

  connect(): void {
    const url = this.taskId
      ? `${WS_BASE}/ws?task_id=${encodeURIComponent(this.taskId)}`
      : `${WS_BASE}/ws`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log("[WS] Connected");
      this.reconnectAttempts = 0;
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        this.handlers.forEach((h) => h(msg));
      } catch (e) {
        console.error("[WS] Parse error:", e);
      }
    };

    this.ws.onclose = () => {
      console.log("[WS] Disconnected");
      this._scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error("[WS] Error:", err);
    };
  }

  private _scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnects) {
      console.warn("[WS] Max reconnect attempts reached");
      return;
    }
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 30_000);
    this.reconnectAttempts++;
    console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  disconnect(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
    this.ws = null;
  }

  subscribe(handler: MessageHandler): () => void {
    this.handlers.add(handler);
    return () => this.handlers.delete(handler);
  }

  send(data: unknown): void {
    this.ws?.send(JSON.stringify(data));
  }
}

let globalClient: WSClient | null = null;

export function getGlobalWS(taskId?: string): WSClient {
  if (!globalClient) {
    globalClient = new WSClient(taskId);
    globalClient.connect();
  }
  return globalClient;
}
