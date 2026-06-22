"""Gmail / Email connector — the tenant's inbox, on the connector kit.

Self-serve and no OAuth infra: the tenant connects with their email + a Google
**App Password** (16 chars, requires 2FA), which we store encrypted per-tenant.
`sync` pulls recent INBOX messages into `mail_messages` (idempotent on Message-ID),
feeding the Support department's triage. Read-only. The blocking IMAP work is
isolated behind helpers (run in a thread, monkeypatchable in tests).
"""
from __future__ import annotations

import asyncio
import email
import imaplib
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from winny_gateway.db import db_insert, db_select
from winny_gateway.integrations.connector import Connector, ConnectorError, register

_HOST = "imap.gmail.com"


def _text(msg: email.message.Message) -> str:
    """Best-effort plain-text body."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                except Exception:  # noqa: BLE001
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")
    except Exception:  # noqa: BLE001
        return str(msg.get_payload())


def _received(raw_date: str | None) -> str | None:
    if not raw_date:
        return None
    try:
        return parsedate_to_datetime(raw_date).isoformat()
    except (TypeError, ValueError):
        return None


def _verify_login(account: str, password: str) -> None:  # blocking
    m = imaplib.IMAP4_SSL(_HOST)
    try:
        m.login(account, password)
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass


def _fetch_messages(account: str, password: str, limit: int = 30) -> list[dict[str, Any]]:  # blocking
    m = imaplib.IMAP4_SSL(_HOST)
    m.login(account, password)
    out: list[dict[str, Any]] = []
    try:
        m.select("INBOX")
        _typ, data = m.search(None, "ALL")
        ids = (data[0].split() if data and data[0] else [])[-limit:]
        for i in reversed(ids):
            _typ, raw = m.fetch(i, "(RFC822)")
            if not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            name, addr = parseaddr(msg.get("From", ""))
            body = _text(msg)
            out.append({
                "external_id": msg.get("Message-ID"),
                "from_name": name or None,
                "from_addr": addr or None,
                "subject": msg.get("Subject"),
                "body": body,
                "received_at": _received(msg.get("Date")),
            })
    finally:
        try:
            m.logout()
        except Exception:  # noqa: BLE001
            pass
    return out


class GmailConnector(Connector):
    provider = "gmail"
    kind = "email"

    async def verify_token(self, token: str, account: str | None = None) -> dict[str, Any]:
        if not account or "@" not in account:
            raise ConnectorError("a Gmail address is required", code="missing_account", status=400)
        try:
            await asyncio.to_thread(_verify_login, account, token)
        except imaplib.IMAP4.error:
            raise ConnectorError("Gmail login failed — use an App Password (2FA required)",
                                 code="invalid_token", status=400)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Gmail unreachable: {exc}", code="network", status=502) from exc
        return {"external_account": account}

    async def sync(self, uid: str, conn: dict[str, Any], token: str) -> dict[str, Any]:
        account = conn.get("external_account")
        if not account:
            raise ConnectorError("connection missing the email address", code="bad_account", status=500)
        try:
            msgs = await asyncio.to_thread(_fetch_messages, account, token, 30)
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(f"Gmail fetch failed: {exc}", code="fetch", status=502) from exc

        existing = await db_select("mail_messages", filters={"user_id": uid}, limit=5000)
        seen = {r.get("external_id") for r in existing if r.get("external_id")}
        added = 0
        for mm in msgs:
            eid = mm.get("external_id")
            if eid and eid in seen:
                continue
            if eid:
                seen.add(eid)
            body = mm.get("body") or ""
            if await db_insert("mail_messages", {
                "user_id": uid, "external_id": eid, "folder": "INBOX",
                "from_addr": mm.get("from_addr"), "from_name": mm.get("from_name"),
                "subject": mm.get("subject"), "snippet": body[:200], "body": body[:8000],
                "received_at": mm.get("received_at"), "status": "unread", "triaged": False,
            }):
                added += 1
        return {"metadata": {"messages": added}, "messages_added": added}


register(GmailConnector())
