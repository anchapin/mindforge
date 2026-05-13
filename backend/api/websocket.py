"""WebSocket connection manager and message protocol.

From SPEC.md Section 2.5 -- WebSocket message protocol.
All outgoing messages pass through scrub() to redact sensitive fields.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------
# Sensitive field redaction
# ---------------------------------------------------------------------------------------

SENSITIVE_KEYS = {
    "auth_token_enc", "refresh_token_enc", "access_token",
    "password", "secret", "api_key", "private_key", "token",
    "authorization", "cookie", "session",
}


def _scrub(obj: dict | list) -> dict | list:
    """Recursively redact sensitive fields in a dict or list."""
    if isinstance(obj, dict):
        return {
            k: "[REDACTED]" if k.lower() in SENSITIVE_KEYS
            else _scrub(v) if isinstance(v, (dict, list))
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
        self._connections: dict[str, WebSocket] = {}  # type: ignore[assignment]
        self._global_connections: list[WebSocket] = []  # type: ignore[assignment]
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, task_id: str | None = None) -> None:
        await websocket.accept()
        async with self._lock:
            if task_id:
                self._connections[task_id] = websocket
            else:
                self._global_connections.append(websocket)

    async def disconnect(self, websocket: WebSocket, task_id: str | None = None) -> None:
        async with self._lock:
            if task_id and task_id in self._connections:
                del self._connections[task_id]
            elif websocket in self._global_connections:
                self._global_connections.remove(websocket)

    async def send(self, task_id: str, message: dict) -> None:
        message = _scrub(message)
        payload = json.dumps(message)
        async with self._lock:
            ws = self._connections.get(task_id)
        if ws:
            try:
                await ws.send_text(payload)
            except Exception as exc:
                logger.warning("WS send failed to task %s: %s", task_id, exc)
                await self.disconnect(ws, task_id)

    async def broadcast(self, message: dict) -> None:
        message = _scrub(message)
        payload = json.dumps(message)
        async with self._lock:
            listeners = list(self._global_connections)
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
        await self.send(task_id, {"type": "task_status_update", "task_id": task_id, "status": status, "agent_role": agent_role})

    async def send_draft_ready(self, task_id: str, node_id: str, draft: dict, approval_deadline_iso: str) -> None:
        await self.send(task_id, {
            "type": "draft_ready", "task_id": task_id, "node_id": node_id,
            "draft": draft, "awaiting_approval": True, "approval_deadline_iso": approval_deadline_iso,
        })

    async def send_approval_resolved(self, task_id: str, node_id: str, action: str) -> None:
        await self.send(task_id, {"type": "approval_resolved", "task_id": task_id, "node_id": node_id, "action": action})

    async def send_clarification_request(self, task_id: str, node_id: str, question: str, options: list[str], context_summary: str, deadline_iso: str) -> None:
        await self.send(task_id, {
            "type": "clarification_request", "task_id": task_id, "node_id": node_id,
            "question": question, "options": options, "context_summary": context_summary, "deadline_iso": deadline_iso,
        })

    async def send_agent_message(self, task_id: str, agent_role: str, message: str) -> None:
        await self.send(task_id, {"type": "agent_message", "task_id": task_id, "agent_role": agent_role, "message": message})

    async def send_task_completed(self, task_id: str, final_output: dict) -> None:
        await self.send(task_id, {"type": "task_completed", "task_id": task_id, "final_output": final_output})

    async def send_task_failed(self, task_id: str, error: str, escalated: bool) -> None:
        await self.send(task_id, {"type": "task_failed", "task_id": task_id, "error": error, "escalated": escalated})

    async def send_skill_triggered(self, skill_id: str, task_id: str) -> None:
        await self.broadcast({"type": "skill_triggered", "skill_id": skill_id, "task_id": task_id})

    async def send_stream_token(self, task_id: str, node_id: str, token: str) -> None:
        await self.send(task_id, {"type": "stream_token", "task_id": task_id, "node_id": node_id, "token": token})


ws_manager = WSConnectionManager()
