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
  | "worker_status_changed"
  | "pong";

export interface WSMessage {
  type: WSMessageType;
  task_id?: string;
  seq?: number;       // #106: incrementing sequence for reliable reconnect
  correlation_id?: string;  // #109: tracing ID for WS operations
  [key: string]: unknown;
}

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000";

type MessageHandler = (msg: WSMessage) => void;

/** Module-level sequence counter for the connected session.
 *  Persists across reconnects so the client can request replay.
 */
let _sessionSeq = 0;

export function getLastSeq(): number {
  return _sessionSeq;
}

/** Store correlation IDs of in-flight WS operations, keyed by correlation_id. */
const _pendingCorrIds = new Map<string, (msg: WSMessage) => void>();

export class WSClient {
  private ws: WebSocket | null = null;
  private handlers: Set<MessageHandler> = new Set();
  private reconnectAttempts = 0;
  private maxReconnects = 5;
  private taskId: string | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private explicitlyDisconnected = false;

  constructor(taskId?: string) {
    this.taskId = taskId ?? null;
  }

  connect(): void {
    this.explicitlyDisconnected = false;
    const url = this.taskId
      ? `${WS_BASE}/ws?task_id=${encodeURIComponent(this.taskId)}`
      : `${WS_BASE}/ws`;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      console.log(`[WS] Connected [last_seq=${_sessionSeq}]`);
      this.reconnectAttempts = 0;
      // #106: on every connect, tell server our last seen seq so it can replay
      this.send({ type: "subscribe", last_sequence: _sessionSeq });
    };

    this.ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        // Track correlation_id for #109
        if (msg.correlation_id) {
          const resolve = _pendingCorrIds.get(msg.correlation_id);
          if (resolve) {
            resolve(msg);
            _pendingCorrIds.delete(msg.correlation_id);
          }
          // Always log with correlation_id for tracing
          if (msg.type !== "stream_token") {
            console.debug(`[WS][corr_id=${msg.correlation_id}] ${msg.type}`, msg);
          }
        }
        // #106: update session sequence when server sends seq
        if (typeof msg.seq === "number" && msg.seq > _sessionSeq) {
          _sessionSeq = msg.seq;
        }
        this.handlers.forEach((h) => h(msg));
      } catch (e) {
        console.error("[WS] Parse error:", e);
      }
    };

    this.ws.onclose = () => {
      console.log("[WS] Disconnected");
      if (!this.explicitlyDisconnected) {
        this._scheduleReconnect();
      }
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
    console.log(`[WS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts}) [last_seq=${_sessionSeq}]`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }

  disconnect(): void {
    this.explicitlyDisconnected = true;
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

  /**
   * #109: Fire-and-forget async request/response over WS.
   * Returns a promise that resolves when a message with the same correlation_id arrives.
   * Times out after `timeoutMs` (default 10s).
   */
  async requestResponse<T extends WSMessage>(
    data: Record<string, unknown>,
    timeoutMs = 10_000,
  ): Promise<T> {
    return new Promise((resolve, reject) => {
      const corrId = (data.correlation_id as string) ?? crypto.randomUUID();
      data.correlation_id = corrId;
      const timer = setTimeout(() => {
        _pendingCorrIds.delete(corrId);
        reject(new Error(`WS request timeout [corr_id=${corrId}]`));
      }, timeoutMs);
      _pendingCorrIds.set(corrId, (msg) => {
        clearTimeout(timer);
        resolve(msg as T);
      });
      this.send(data);
    });
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

export function resetGlobalWS(): void {
  globalClient?.disconnect();
  globalClient = null;
  _sessionSeq = 0;
}
