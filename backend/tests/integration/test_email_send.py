"""Integration tests for EmailSendTool (#42).

Approach: monkeypatch `aiosmtplib.send` so we can assert what would have
been sent without spinning up a real SMTP server. This is sufficient
because the real network behavior is aiosmtplib's contract, not ours;
what we own is the message construction, recipient handling, and
high-stakes registration.
"""

from __future__ import annotations

# ----- pre-import patches (mirrors test_integrations_api.py) ---------------
import os
import pathlib

_ORIGINAL_MAKEDIRS = os.makedirs


def _safe_makedirs(path, *args, **kwargs):
    if isinstance(path, pathlib.Path):
        path = str(path)
    if str(path).startswith("/app"):
        return
    return _ORIGINAL_MAKEDIRS(path, *args, **kwargs)


os.makedirs = _safe_makedirs  # type: ignore[assignment]
# --------------------------------------------------------------------------

import sys  # noqa: E402

import pytest  # noqa: E402

from backend.tools.email_send import EmailSendTool  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CapturingAioSmtplib:
    """Stand-in for the aiosmtplib module. Records every send() call."""

    sent: list[dict] = []

    @staticmethod
    async def send(
        message,
        *,
        hostname,
        port,
        username,
        password,
        start_tls,
        use_tls,
        recipients,
    ):
        _CapturingAioSmtplib.sent.append(
            {
                "message": message,
                "hostname": hostname,
                "port": port,
                "username": username,
                "password": password,
                "start_tls": start_tls,
                "use_tls": use_tls,
                "recipients": list(recipients) if recipients is not None else None,
            }
        )


@pytest.fixture(autouse=True)
def _reset_capture():
    _CapturingAioSmtplib.sent.clear()
    yield
    _CapturingAioSmtplib.sent.clear()


@pytest.fixture
def fake_smtp(monkeypatch):
    """Inject _CapturingAioSmtplib in place of the real aiosmtplib."""
    monkeypatch.setitem(sys.modules, "aiosmtplib", _CapturingAioSmtplib)
    return _CapturingAioSmtplib


def _common_creds() -> dict:
    return {
        "host": "smtp.example.com",
        "port": 587,
        "username": "alice@example.com",
        "password": "hunter2",
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSend:
    @pytest.mark.asyncio
    async def test_minimal_send_succeeds(self, fake_smtp):
        result = await EmailSendTool().execute(
            action="send",
            to="bob@example.com",
            subject="Hello",
            body="Hi Bob.",
            **_common_creds(),
        )
        assert result.success, result.error
        assert result.data["to"] == "bob@example.com"
        assert result.data["subject"] == "Hello"
        # The actual aiosmtplib.send was called once
        assert len(fake_smtp.sent) == 1
        sent = fake_smtp.sent[0]
        assert sent["hostname"] == "smtp.example.com"
        assert sent["port"] == 587
        assert sent["username"] == "alice@example.com"
        # recipients includes the To
        assert "bob@example.com" in sent["recipients"]

    @pytest.mark.asyncio
    async def test_cc_and_bcc_routed_to_envelope(self, fake_smtp):
        await EmailSendTool().execute(
            action="send",
            to="bob@example.com",
            cc=["carol@example.com", "dave@example.com"],
            bcc="eve@example.com",
            subject="Multi",
            body="Multi-recipient send",
            **_common_creds(),
        )
        sent = fake_smtp.sent[0]
        # All three lists end up in the envelope-level recipient set
        assert "bob@example.com" in sent["recipients"]
        assert "carol@example.com" in sent["recipients"]
        assert "dave@example.com" in sent["recipients"]
        assert "eve@example.com" in sent["recipients"]

        # CC is in the headers, BCC is NOT (so the recipient can't see it)
        message = sent["message"]
        assert "carol@example.com" in message["Cc"]
        # 'Bcc' header must not exist on the wire
        assert message.get("Bcc") is None

    @pytest.mark.asyncio
    async def test_attachment_included(self, fake_smtp):
        await EmailSendTool().execute(
            action="send",
            to="bob@example.com",
            subject="With attachment",
            body="See attached.",
            attachments=[
                {
                    "filename": "report.txt",
                    "content": b"hello world",
                    "mime_type": "text/plain",
                }
            ],
            **_common_creds(),
        )
        message = fake_smtp.sent[0]["message"]
        # Walk the parts and look for our attachment
        attached = list(message.iter_attachments())
        assert len(attached) == 1
        assert attached[0].get_filename() == "report.txt"
        assert attached[0].get_payload(decode=True) == b"hello world"

    @pytest.mark.asyncio
    async def test_use_ssl_implicit(self, fake_smtp):
        """use_ssl=True -> implicit SSL on connect (port 465 default)."""
        await EmailSendTool().execute(
            action="send",
            to="bob@example.com",
            subject="SSL",
            body="hi",
            use_ssl=True,
            host="smtp.example.com",
            port=None,  # let the tool pick the SSL default
            username="alice@example.com",
            password="hunter2",
        )
        sent = fake_smtp.sent[0]
        assert sent["use_tls"] is True
        assert sent["start_tls"] is False
        assert sent["port"] == 465


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrors:
    @pytest.mark.asyncio
    async def test_unknown_action(self, fake_smtp):
        result = await EmailSendTool().execute(
            action="explode", to="x@y.z", subject="s", body="b", **_common_creds()
        )
        assert result.success is False
        assert "Unknown action" in result.error
        # No SMTP call attempted
        assert fake_smtp.sent == []

    @pytest.mark.asyncio
    async def test_missing_required_field(self, fake_smtp):
        result = await EmailSendTool().execute(
            action="send", to="x@y.z", subject="s", body="b"  # no creds
        )
        assert result.success is False
        assert "Missing required field" in result.error
        assert fake_smtp.sent == []

    @pytest.mark.asyncio
    async def test_aiosmtplib_not_installed_returns_clean_error(self, monkeypatch):
        """If the optional dep isn't present, we fail closed with a clear
        message instead of crashing inside the tool."""
        # Pretend aiosmtplib import fails
        import builtins

        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "aiosmtplib":
                raise ImportError("No module named 'aiosmtplib' (test)")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        result = await EmailSendTool().execute(
            action="send",
            to="bob@example.com",
            subject="hi",
            body="hi",
            **_common_creds(),
        )
        assert result.success is False
        assert "aiosmtplib" in result.error

    @pytest.mark.asyncio
    async def test_smtp_failure_propagates_as_tool_failure(self, monkeypatch):
        class BoomLib:
            @staticmethod
            async def send(*a, **kw):
                raise OSError("connection refused")

        monkeypatch.setitem(sys.modules, "aiosmtplib", BoomLib)

        result = await EmailSendTool().execute(
            action="send",
            to="bob@example.com",
            subject="hi",
            body="hi",
            **_common_creds(),
        )
        assert result.success is False
        assert "connection refused" in result.error


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


class TestWiring:
    def test_registered_via_register_all_tools(self):
        from backend.tools.registry import ToolRegistry, register_all_tools

        ToolRegistry._tools.clear()
        try:
            register_all_tools()
            tool = ToolRegistry.get("email_send")
            assert isinstance(tool, EmailSendTool)
        finally:
            ToolRegistry._tools.clear()

    def test_listed_as_high_stakes(self):
        """The supervisor's approval-gate set must include the new send action
        so memory-dominated email sends trigger the human-approval cycle."""
        from backend.agents.supervisor import _HIGH_STAKES_ACTIONS

        assert "email_send.send" in _HIGH_STAKES_ACTIONS or "send_email" in _HIGH_STAKES_ACTIONS

    def test_email_rate_limit_present(self):
        from backend.tools.rate_limiter import INTEGRATION_LIMITS

        assert "email" in INTEGRATION_LIMITS
        assert INTEGRATION_LIMITS["email"] >= 1
