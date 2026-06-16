"""Himalaya transport bridge — pulls envelopes from a configured mailbox.

`himalaya` (https://github.com/pimalaya/himalaya) is a CLI IMAP/SMTP client.
When it's installed and configured on the host we shell out to it to list
envelopes as JSON; otherwise this degrades to an explicit "unavailable" result
so the Mail surface never crashes on a host without a mailbox wired up.

Config (env):
    WINNY_HIMALAYA_BIN      path to the himalaya binary (default: "himalaya")
    WINNY_HIMALAYA_ACCOUNT  account name to pass with `-a` (optional)

We deliberately only READ envelopes here — sending is review-then-send through
the drafts surface, never auto-dispatched.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from typing import Any

from winny_gateway.logging import get_logger

logger = get_logger(__name__)


def _bin() -> str | None:
    name = os.getenv("WINNY_HIMALAYA_BIN", "himalaya")
    return shutil.which(name) or (name if os.path.isabs(name) and os.path.exists(name) else None)


def available() -> bool:
    return _bin() is not None


async def list_envelopes(folder: str = "INBOX", limit: int = 50) -> dict[str, Any]:
    """Return {available, messages, reason?}. Never raises."""
    binary = _bin()
    if binary is None:
        return {"available": False, "messages": [], "reason": "himalaya_not_installed"}

    args = [binary]
    account = os.getenv("WINNY_HIMALAYA_ACCOUNT")
    if account:
        args += ["-a", account]
    # himalaya 1.x: `envelope list -o json -f <folder> -s <page-size>`
    args += ["envelope", "list", "-o", "json", "-f", folder, "-s", str(limit)]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
    except (OSError, asyncio.TimeoutError) as exc:
        logger.warning("himalaya exec failed: %s", exc, extra={"component": "mail"})
        return {"available": True, "messages": [], "reason": f"exec_failed: {exc}"}

    if proc.returncode != 0:
        reason = (err or b"").decode(errors="replace").strip()[:300] or f"exit {proc.returncode}"
        return {"available": True, "messages": [], "reason": reason}

    try:
        raw = json.loads((out or b"").decode(errors="replace") or "[]")
    except json.JSONDecodeError as exc:
        return {"available": True, "messages": [], "reason": f"bad_json: {exc}"}

    return {"available": True, "messages": [_map_envelope(e, folder) for e in raw], "reason": None}


def _map_envelope(env: dict[str, Any], folder: str) -> dict[str, Any]:
    """Map a himalaya envelope onto our mail_messages ingest shape (transport
    versions differ in field names, so we read defensively)."""
    frm = env.get("from") or {}
    if isinstance(frm, str):
        from_name, from_addr = None, frm
    else:
        from_name = frm.get("name")
        from_addr = frm.get("addr") or frm.get("address")
    flags = env.get("flags") or []
    seen = "Seen" in flags or "seen" in [str(f).lower() for f in flags]
    return {
        "external_id": str(env.get("id") or env.get("internal_id") or ""),
        "folder": folder,
        "from_addr": from_addr,
        "from_name": from_name,
        "subject": env.get("subject"),
        "snippet": env.get("subject"),  # envelope list carries no body; snippet=subject until fetched
        "received_at": env.get("date"),
        "status": "read" if seen else "unread",
    }
