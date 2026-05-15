"""WebSocket connection manager and message protocol.

From SPEC.md Section 2.5 -- WebSocket message protocol.
All outgoing messages pass through scrub() to redact sensitive fields.

Issue #106 — sequence numbers for reliable reconnect:
  - Every broadcast/send carries an incrementing "seq" field.
  - Per-connection state tracks "last_sent_seq" per WebSocket.
  - On connect, clients may send {"type":"subscribe","last_sequence":N}
    to request replay from seq N+1.
  - Server maintains a small replay buffer (last 100 messages by default).

Issue #109 — correlation IDs for observability:
  - Every outbound message carries a "correlation_id" (UUID4).
  - Correlation IDs appear in server logs for tracing WS operations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Sensitive field redaction
# ---------------------------------------------------------------------------------------

SENSITIVE_KEYS = {
    "auth_token_enc",
    "refresh_token_enc",
    "access_token",
    "password",
    "secret",
    "api_key",
    "private_key",
    "token",
    "authorization",
    "cookie",
    "session",
}


def _scrub(obj: dict | list) -> dict | list:
    """Recursively redact sensitive fields in a dict or list."""
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]"
            if k.lower() in SENSITIVE_KEYS
            else _scrub(v)
            if isinstance(v, (dict, list))
            else v
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [_scrub(i) for i in obj]
    return obj


# ---------------------------------------------------------------------------------------
# Replay buffer
# ---------------------------------------------------------------------------------------

DEFAULT_REPLAY_BUFFER_SIZE = 100


class _ReplayBuffer:
    """Circular buffer of the last N outbound messages for reconnect replay."""

    def __init__(self, maxsize: int = DEFAULT_REPLAY_BUFFER_SIZE) -> None:
        self.maxsize = maxsize
        self._buf: deque[dict[str, Any]] = deque(maxlen=maxsize)

    def append(self, msg: dict[str, Any]) -> None:
        self._buf.append(msg)

    def after(self, seq: int) -> list[dict[str, Any]]:
        """Return messages with seq > seq (i.e., from seq+1 onward)."""
        return [m for m in self._buf if m.get("seq", 0) > seq]


# ---------------------------------------------------------------------------------------
# Per-connection state
# ---------------------------------------------------------------------------------------


class _ConnectionState:
    """Lightweight state tracked per WebSocket connection."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.last_sequence = 0


# ---------------------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------------------


class WSConnectionManager:
    """Manages WebSocket connections from the dashboard.

    All agent events are broadcast through this manager.
    All outgoing messages are scrubbed of sensitive fields.

    Issue #106: every send/broadcast carries a globally incrementing
    sequence number so clients can request replay on reconnect.
    Issue #109: every message carries a correlation_id for observability.
    """

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}  # type: ignore[assignment]
        self._global_connections: list[WebSocket] = []  # type: ignore[assignment]
        # Per-connection state (parallel arrays for lock-free access where possible)
        self._conn_states: dict[WebSocket, _ConnectionState] = {}
        self._global_states: list[_ConnectionState] = []
        self._lock = asyncio.Lock()
        self._seq = 0
        self._replay = _ReplayBuffer()

    # -----------------------------------------------------------------
    # Sequence helpers
    # -----------------------------------------------------------------

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _stamp(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Add seq + correlation_id to an outbound message."""
        msg = dict(msg)
        msg["seq"] = self._next_seq()
        msg["correlation_id"] = str(uuid.uuid4())
        self._replay.append(msg)
        return msg

    # -----------------------------------------------------------------
    # Connection lifecycle
    # -----------------------------------------------------------------

    async def connect(self, websocket: WebSocket, task_id: str | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            state = _ConnectionState(websocket)
            if task_id:
                self._connections[task_id] = websocket
            else:
                self._global_connections.append(websocket)
                self._global_states.append(state)
            self._conn_states[websocket] = state
        try:
            from backend.observability.metrics import inc_ws_connection

            inc_ws_connection()
        except Exception:
            pass

    async def disconnect(self, websocket: WebSocket, task_id: str | None = None) -> None:
        removed = False
        async with self._lock:
            if task_id and task_id in self._connections:
                del self._connections[task_id]
                removed = True
            elif websocket in self._global_connections:
                idx = self._global_connections.index(websocket)
                self._global_connections.pop(idx)
                if idx < len(self._global_states):
                    self._global_states.pop(idx)
                removed = True
            self._conn_states.pop(websocket, None)
        if removed:
            try:
                from backend.observability.metrics import dec_ws_connection

                dec_ws_connection()
            except Exception:
                pass

    # -----------------------------------------------------------------
    # Inbound message handling (client → server)
    # -----------------------------------------------------------------

    async def handle_message(self, websocket: WebSocket, task_id: str | None, data: dict[str, Any]) -> None:
        """Process inbound client messages.

        Supported:
          - {"type":"subscribe","last_sequence":N}
              Request replay of all messages after sequence N.
              Sent automatically by the frontend on reconnect.
        """
        msg_type = data.get("type")
        if msg_type == "subscribe":
            last_seq = int(data.get("last_sequence", 0))
            async with self._lock:
                state = self._conn_states.get(websocket)
                if state:
                    state.last_sequence = last_seq
            # Replay missed messages to this connection
            missed = self._replay.after(last_seq)
            logger.info(
                "[WS] client replay request last_seq=%d => %d messages (corr_id=%s)",
                last_seq,
                len(missed),
                data.get("correlation_id", "?"),
            )
            for msg in missed:
                try:
                    await websocket.send_text(json.dumps(msg))
                except Exception as exc:
                    logger.warning("replay send failed: %s", exc)
        elif msg_type == "ping":
            # Client-side heartbeat echo
            await websocket.send_text(json.dumps({"type": "pong", "correlation_id": data.get("correlation_id", "")}))

    # -----------------------------------------------------------------
    # Outbound sending
    # -----------------------------------------------------------------

    async def send(self, task_id: str, message: dict) -> None:
        message = _scrub(message)  # type: ignore[assignment]
        stamped = self._stamp(message)  # adds seq + correlation_id
        corr_id = stamped.get("correlation_id", "?")
        payload = json.dumps(stamped)
        async with self._lock:
            ws: WebSocket | None = self._connections.get(task_id)  # type: ignore[assignment,annotation-unchecked]
            if ws:
                state = self._conn_states.get(ws)
                if state:
                    state.last_sequence = stamped["seq"]
        if ws:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.warning("WS send failed to task %s: %s [corr_id=%s]", task_id, exc, corr_id)
                await self.disconnect(ws, task_id)

    async def broadcast(self, message: dict) -> None:
        message = _scrub(message)  # type: ignore[assignment]
        stamped = self._stamp(message)
        corr_id = stamped.get("correlation_id", "?")
        payload = json.dumps(stamped)
        async with self._lock:
            listeners: list[WebSocket] = list(self._global_connections)  # type: ignore[assignment,annotation-unchecked]
            for ws in listeners:
                state = self._conn_states.get(ws)
                if state:
                    state.last_sequence = stamped["seq"]
        for ws in listeners:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.warning("WS broadcast failed: %s [corr_id=%s]", exc, corr_id)
                async with self._lock:
                    if ws in self._global_connections:
                        idx = self._global_connections.index(ws)
                        self._global_connections.pop(idx)
                        if idx < len(self._global_states):
                            self._global_states.pop(idx)
                        self._conn_states.pop(ws, None)

    # -----------------------------------------------------------------
    # Public send helpers (mirrors original API, adds seq + correlation_id)
    # -----------------------------------------------------------------

    async def send_task_created(self, task_id: str, skill_name: str | None) -> None:
        await self.broadcast({"type": "task_created", "task_id": task_id, "skill_name": skill_name})

    async def send_task_status_update(self, task_id: str, status: str, agent_role: str) -> None:
        await self.send(
            task_id,
            {
                "type": "task_status_update",
                "task_id": task_id,
                "status": status,
                "agent_role": agent_role,
            },
        )

    async def send_draft_ready(
        self, task_id: str, node_id: str, draft: dict, approval_deadline_iso: str
    ) -> None:
        await self.send(
            task_id,
            {
                "type": "draft_ready",
                "task_id": task_id,
                "node_id": node_id,
                "draft": draft,
                "awaiting_approval": True,
                "approval_deadline_iso": approval_deadline_iso,
            },
        )

    async def send_approval_resolved(self, task_id: str, node_id: str, action: str) -> None:
        await self.send(
            task_id,
            {"type": "approval_resolved", "task_id": task_id, "node_id": node_id, "action": action},
        )

    async def send_clarification_request(
        self,
        task_id: str,
        node_id: str,
        question: str,
        options: list[str],
        context_summary: str,
        deadline_iso: str,
    ) -> None:
        await self.send(
            task_id,
            {
                "type": "clarification_request",
                "task_id": task_id,
                "node_id": node_id,
                "question": question,
                "options": options,
                "context_summary": context_summary,
                "deadline_iso": deadline_iso,
            },
        )

    async def send_agent_message(self, task_id: str, agent_role: str, message: str) -> None:
        await self.send(
            task_id,
            {
                "type": "agent_message",
                "task_id": task_id,
                "agent_role": agent_role,
                "message": message,
            },
        )

    async def send_task_completed(self, task_id: str, final_output: dict) -> None:
        await self.send(
            task_id, {"type": "task_completed", "task_id": task_id, "final_output": final_output}
        )

    async def send_task_failed(self, task_id: str, error: str, escalated: bool) -> None:
        await self.send(
            task_id,
            {"type": "task_failed", "task_id": task_id, "error": error, "escalated": escalated},
        )

    async def send_skill_triggered(self, skill_id: str, task_id: str) -> None:
        await self.broadcast({"type": "skill_triggered", "skill_id": skill_id, "task_id": task_id})

    async def send_stream_token(self, task_id: str, node_id: str, token: str) -> None:
        await self.send(
            task_id,
            {"type": "stream_token", "task_id": task_id, "node_id": node_id, "token": token},
        )


ws_manager = WSConnectionManager()
