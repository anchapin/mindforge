"""SMTP email send tool — Phase 1 (no OAuth) (#42).

Uses aiosmtplib for non-blocking send. Falls back gracefully if the
optional aiosmtplib dependency isn't installed (returns a clear error
rather than crashing on import — keeps the rest of the platform usable).

The `subscription-refund` skill references this tool; without it the
'negotiate' node has no way to deliver the drafted email after approval.

This tool is HIGH-STAKES — it performs an external action (sends a real
message). Per SPEC §3b.8 Layer 3, the calling skill node MUST set
`requires_approval: true`. The supervisor's `_HIGH_STAKES_ACTIONS` set
must also include `send_email` so the approval gate fires when the
proposed action came from memory-dominated context.
"""

from __future__ import annotations

import logging
import time
from email.message import EmailMessage
from typing import Any

from .base import BaseTool, ToolResult
from .rate_limiter import integration_call

logger = logging.getLogger(__name__)

# Action names used in skill YAML (also exported for the supervisor's
# _HIGH_STAKES_ACTIONS membership check)
ACTION_SEND = "send"


class EmailSendTool(BaseTool):  # type: ignore[override]
    """Send an email via SMTP (TLS by default).

    Required kwargs (per execute):
      action="send"
      host, port, username, password   (SMTP credentials)
      to, subject, body                 (message)

    Optional:
      cc, bcc           (list[str])
      reply_to          (str)
      use_tls           (bool, default True)  — STARTTLS upgrade
      use_ssl           (bool, default False) — implicit SSL on connect
      attachments       (list[dict] with keys: filename, content (bytes), mime_type)

    The tool DOES NOT decide WHEN to send. It only sends what it's given,
    after the skill executor has cleared the approval gate.
    """

    name = "email_send"
    description = "Send an email via SMTP (after human approval — high-stakes)"
    required_integrations = ["email"]

    async def _execute(self, action: str, **kwargs) -> ToolResult:  # type: ignore[override]
        start = time.monotonic()
        if action != ACTION_SEND:
            return ToolResult(
                success=False,
                error=f"Unknown action: {action!r}. Supported: 'send'.",
                latency_ms=(time.monotonic() - start) * 1000,
                tool_name=self.name,
            )

        # Validate required fields up front so we fail fast and don't open a
        # connection just to discover the body is missing.
        required = ("host", "username", "password", "to", "subject", "body")
        missing = [k for k in required if not kwargs.get(k)]
        if missing:
            return ToolResult(
                success=False,
                error=f"Missing required field(s): {', '.join(missing)}",
                latency_ms=(time.monotonic() - start) * 1000,
                tool_name=self.name,
            )

        try:
            message = self._build_message(kwargs)
        except Exception as exc:
            logger.warning("EmailSendTool message-build failed: %s", exc)
            return ToolResult(
                success=False,
                error=f"Could not build message: {exc}",
                latency_ms=(time.monotonic() - start) * 1000,
                tool_name=self.name,
            )

        try:
            await integration_call("email", self._send, message, kwargs)
        except ImportError as exc:
            return ToolResult(
                success=False,
                error=f"aiosmtplib not installed; install backend extras to send mail ({exc})",
                latency_ms=(time.monotonic() - start) * 1000,
                tool_name=self.name,
            )
        except Exception as exc:
            logger.exception("EmailSendTool send failed")
            return ToolResult(
                success=False,
                error=str(exc),
                latency_ms=(time.monotonic() - start) * 1000,
                tool_name=self.name,
            )

        return ToolResult(
            success=True,
            data={
                "to": message["To"],
                "subject": message["Subject"],
                "message_id": message["Message-ID"] or "",
                "size_bytes": len(message.as_bytes()),
            },
            latency_ms=(time.monotonic() - start) * 1000,
            tool_name=self.name,
        )

    async def validate_auth(self, token: str | None = None) -> bool:
        """SMTP auth is verified at connect time inside execute(). A
        standalone probe would need host+port+username+password which
        we don't have here. Returning True keeps the interface uniform
        without making claims we can't back up."""
        del token  # unused
        return True

    # ------------------------------------------------------------------
    # Helpers — module-private; not for external use
    # ------------------------------------------------------------------

    @staticmethod
    def _to_recipient_list(value: Any) -> list[str]:
        """Accept either a comma-separated string or a list of addresses."""
        if value is None:
            return []
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        return [str(value)]

    @classmethod
    def _build_message(cls, kwargs: dict[str, Any]) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = kwargs.get("from") or kwargs["username"]
        msg["To"] = ", ".join(cls._to_recipient_list(kwargs["to"]))
        cc_list = cls._to_recipient_list(kwargs.get("cc"))
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        # Bcc is intentionally NOT placed in headers; passed to send() only.
        if kwargs.get("reply_to"):
            msg["Reply-To"] = kwargs["reply_to"]
        msg["Subject"] = kwargs["subject"]
        msg.set_content(kwargs["body"])

        for att in kwargs.get("attachments") or []:
            filename = att.get("filename", "attachment.bin")
            content = att.get("content", b"")
            mime = (att.get("mime_type") or "application/octet-stream").split("/", 1)
            maintype = mime[0]
            subtype = mime[1] if len(mime) > 1 else "octet-stream"
            if isinstance(content, str):
                content = content.encode()
            msg.add_attachment(
                content, maintype=maintype, subtype=subtype, filename=filename
            )
        return msg

    @staticmethod
    async def _send(message: EmailMessage, kwargs: dict[str, Any]) -> None:
        """Open an SMTP connection and dispatch. Imported lazily so the
        rest of the platform doesn't require aiosmtplib at import time."""
        import aiosmtplib

        host = kwargs["host"]
        port = int(kwargs.get("port") or (465 if kwargs.get("use_ssl") else 587))
        username = kwargs["username"]
        password = kwargs["password"]
        use_tls = kwargs.get("use_tls", not kwargs.get("use_ssl", False))
        use_ssl = kwargs.get("use_ssl", False)

        bcc_list = EmailSendTool._to_recipient_list(kwargs.get("bcc"))
        all_recipients = (
            EmailSendTool._to_recipient_list(message["To"])
            + EmailSendTool._to_recipient_list(message.get("Cc"))
            + bcc_list
        )

        await aiosmtplib.send(
            message,
            hostname=host,
            port=port,
            username=username,
            password=password,
            start_tls=bool(use_tls and not use_ssl),
            use_tls=bool(use_ssl),
            recipients=all_recipients,
        )
