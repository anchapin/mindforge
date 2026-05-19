"""WebSocket connection manager and message protocol.

From SPEC.md Section 2.5 -- WebSocket message protocol.
All outgoing messages pass through scrub() to redact sensitive fields.
"""

from __future__ import annotations

import asyncio
import collections
import json
import logging

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
# Connection manager
# ---------------------------------------------------------------------------------------


class WSConnectionManager:
    """Manages WebSocket connections from the dashboard.

    All agent events are broadcast through this manager.
    All outgoing messages are scrubbed of sensitive fields.
    """

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}  # type: ignore[assignment,annotation-unchecked]
        self._global_connections: list[WebSocket] = []  # type: ignore[assignment,annotation-unchecked]
        self._lock = asyncio.Lock()
        self._next_seq = 1
        self._history = collections.deque(maxlen=1000)

    def _assign_seq(self, message: dict, is_broadcast: bool = False) -> dict:
        """Assign next sequence number and add to history."""
        message["seq"] = self._next_seq
        if is_broadcast:
            message["_broadcast"] = True
        self._next_seq += 1
        self._history.append(message)
        return message

    async def connect(self, websocket: WebSocket, task_id: str | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            if task_id:
                self._connections[task_id] = websocket
            else:
                self._global_connections.append(websocket)
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
                self._global_connections.remove(websocket)
                removed = True
        if removed:
            try:
                from backend.observability.metrics import dec_ws_connection

                dec_ws_connection()
            except Exception:
                pass

    async def send(self, task_id: str, message: dict) -> None:
        message = _scrub(message)  # type: ignore[assignment]
        async with self._lock:
            message = self._assign_seq(message, is_broadcast=False)
            payload = json.dumps(message)
            ws: WebSocket | None = self._connections.get(task_id)  # type: ignore[assignment,annotation-unchecked]
        if ws:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.warning("WS send failed to task %s: %s", task_id, exc)
                await self.disconnect(ws, task_id)

    async def broadcast(self, message: dict) -> None:
        message = _scrub(message)  # type: ignore[assignment]
        async with self._lock:
            message = self._assign_seq(message, is_broadcast=True)
            payload = json.dumps(message)
            listeners: list[WebSocket] = list(self._global_connections)  # type: ignore[assignment,annotation-unchecked]
        for ws in listeners:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.warning("WS broadcast failed: %s", exc)
                async with self._lock:
                    if ws in self._global_connections:
                        self._global_connections.remove(ws)

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

    async def handle_message(self, websocket: WebSocket, task_id: str | None = None, data: dict | None = None) -> None:
        """Handle inbound client messages: subscribe (replay), ping (heartbeat)."""
        if data is None:
            return
        msg_type = data.get("type")
        if msg_type == "subscribe":
            last_seq = data.get("last_sequence", 0)
            logger.debug("[WS] Client subscribing from seq=%d (task_id=%s)", last_seq, task_id)
            await self._replay_events(websocket, last_seq, task_id)
        elif msg_type == "ping":
            await websocket.send_text(json.dumps({"type": "pong"}))
        else:
            logger.debug("[WS] Unknown client message type: %s", msg_type)

    async def _replay_events(self, websocket: WebSocket, last_seq: int, task_id: str | None) -> None:
        """Replay missed events from history."""
        async with self._lock:
            history = list(self._history)
        
        if not history:
            return

        # Gap detection
        if last_seq > 0 and history[0].get("seq", 0) > last_seq + 1:
            logger.warning(
                "[WS] Sequence gap detected for %s: client at %d, history starts at %d",
                task_id or "global",
                last_seq,
                history[0].get("seq"),
            )
        
        replayed = 0
        for msg in history:
            msg_seq = msg.get("seq", 0)
            if msg_seq > last_seq:
                is_msg_broadcast = msg.get("_broadcast", False)
                msg_task_id = msg.get("task_id")
                
                # Routing logic:
                # 1. Message was a broadcast -> everyone gets it.
                # 2. Message was targeted to a task -> only that task client gets it.
                # Note: Global clients currently only receive broadcasts in real-time 'send',
                # so we match that here.
                
                should_send = False
                if is_msg_broadcast:
                    should_send = True
                elif task_id and task_id == msg_task_id:
                    should_send = True
                
                if should_send:
                    try:
                        await websocket.send_text(json.dumps(msg))
                        replayed += 1
                    except Exception:
                        break
        
        if replayed > 0:
            logger.info(
                "[WS] Replayed %d events to %s (last_seq=%d)", 
                replayed, 
                task_id or "global", 
                last_seq
            )

    async def send_skill_triggered(self, skill_id: str, task_id: str) -> None:
        await self.broadcast({"type": "skill_triggered", "skill_id": skill_id, "task_id": task_id})

    async def send_stream_token(self, task_id: str, node_id: str, token: str) -> None:
        await self.send(
            task_id,
            {"type": "stream_token", "task_id": task_id, "node_id": node_id, "token": token},
        )


ws_manager = WSConnectionManager()
