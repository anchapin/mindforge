"""IMAP email fetch tool -- Phase 1 (no OAuth)."""

from __future__ import annotations

import email
import imaplib
import logging
import time
from email.header import decode_header

from .base import BaseTool, ToolResult
from .rate_limiter import integration_call

logger = logging.getLogger(__name__)


def _decode_header_value(value: str) -> str:
    parts = decode_header(value)
    decoded = []
    for content, charset in parts:
        if isinstance(content, bytes):
            decoded.append(content.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(content)
    return " ".join(decoded)


class EmailFetchTool(BaseTool):  # type: ignore[override]
    name = "email_fetch"
    description = "Fetch emails from IMAP inbox (read-only)"
    required_integrations = ["email"]

    async def execute(self, action: str, agent_role: str | None = None, **kwargs) -> ToolResult:  # noqa: C901  # type: ignore[override]
        import asyncio

        start = time.monotonic()

        # Permission enforcement — block unauthorized agents before any network call
        if agent_role is not None:
            self.check_permissions(agent_role, action)

        # OAuth-aware path (#57 part C): when the caller asks for the
        # Composio broker, dispatch through the Composio surface and skip
        # IMAP entirely. Per AGENTS.md Rule 6 / SPEC §5.4 this stays
        # opt-in -- omitting oauth_broker (or passing "none"/"imap")
        # preserves the Phase 1 IMAP fallback used by the email-monitor
        # workflow today.
        oauth_broker = (kwargs.pop("oauth_broker", "") or "").strip().lower()
        if oauth_broker == "composio":
            from .integrations.composio import (
                COMPOSIO_DISABLED_ERROR,
                COMPOSIO_MISSING_CREDENTIAL_ERROR,
                COMPOSIO_NOT_IMPLEMENTED_ERROR,
            )
            from .integrations.composio import _api_key as _composio_key
            from .integrations.composio import _flag_enabled as _composio_flag

            if not _composio_flag():
                return ToolResult(
                    success=False,
                    error=COMPOSIO_DISABLED_ERROR,
                    tool_name=self.name,
                    latency_ms=(time.monotonic() - start) * 1000.0,
                )
            if _composio_key() is None:
                return ToolResult(
                    success=False,
                    error=COMPOSIO_MISSING_CREDENTIAL_ERROR,
                    tool_name=self.name,
                    latency_ms=(time.monotonic() - start) * 1000.0,
                )
            # SDK drop-in goes here. Until then the structured stub keeps
            # the skill executor honest -- no silent IMAP fallback when
            # OAuth was explicitly requested.
            return ToolResult(
                success=False,
                error=COMPOSIO_NOT_IMPLEMENTED_ERROR,
                tool_name=self.name,
                latency_ms=(time.monotonic() - start) * 1000.0,
            )


        host = kwargs.get("host", "imap.gmail.com")
        port = kwargs.get("port", 993)
        username = kwargs.get("username", "")
        password = kwargs.get("password", "")

        def _sync_fetch():
            try:
                mail = imaplib.IMAP4_SSL(host, port)
                mail.login(username, password)
                mail.select("inbox")

                if action == "recent":
                    _, msgs = mail.search(None, "ALL")
                    msg_ids = msgs[0].split()
                    recent = msg_ids[-kwargs.get("limit", 20) :] if msg_ids else []
                    emails = []
                    for mid in reversed(recent):
                        _, data = mail.fetch(mid, "(RFC822)")
                        msg = email.message_from_bytes(data[0][1])
                        emails.append(
                            {
                                "from": _decode_header_value(msg.get("From", "")),
                                "subject": _decode_header_value(msg.get("Subject", "")),
                                "date": msg.get("Date", ""),
                                "body": self._extract_body(msg),
                            }
                        )
                    mail.logout()
                    return ToolResult(
                        success=True,
                        data={"emails": emails},
                        latency_ms=(time.monotonic() - start) * 1000,
                    )
                else:
                    mail.logout()
                    return ToolResult(
                        success=False,
                        error=f"Unknown action: {action}",
                        latency_ms=(time.monotonic() - start) * 1000,
                    )

            except Exception as exc:
                logger.exception("Email fetch error")
                return ToolResult(
                    success=False, error=str(exc), latency_ms=(time.monotonic() - start) * 1000
                )

        async def _run_sync_fetch() -> ToolResult:
            return await asyncio.get_event_loop().run_in_executor(None, _sync_fetch)

        return await integration_call("gmail", _run_sync_fetch)

    async def validate_auth(self, token: str | None = None) -> bool:
        # IMAP/SMTP auth is verified at connect time inside execute(); a
        # standalone probe would require host+port+user which we don't have
        # here. Returning True keeps the interface uniform without making
        # claims we can't back up.
        del token  # unused
        return True

    def _extract_body(self, msg) -> str:
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                    break
        else:
            charset = msg.get_content_charset() or "utf-8"
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        return body[:500]
