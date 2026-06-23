"""Notion connector — the Operations system-of-record, on the connector kit.

Token-based (a Notion internal-integration token, per-tenant, encrypted via the kit —
no OAuth-callback infra). `sync` pulls the pages the integration can see into our
existing `commitments` table (source='notion', idempotent on the Notion page id), so
the Operations department's open-items digest counts real tasks, not just
meeting-derived action items. Read-only.

Notion's data model is freeform, so we stay deliberately simple and robust: each
shared page is an action item (its title becomes the commitment text); a page whose
status/checkbox property reads "done" closes the matching commitment. We never try to
interpret arbitrary schemas beyond that.
"""
from __future__ import annotations

from typing import Any

import httpx

from winny_gateway.db import db_insert, db_select, db_update
from winny_gateway.integrations.connector import Connector, ConnectorError, register

_API = "https://api.notion.com"
_VERSION = "2022-06-28"
_DONE = {"done", "complete", "completed", "closed", "shipped", "archived", "cancelled", "canceled"}
_DONE_PROP_HINTS = ("done", "complete", "completed", "shipped", "checked")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Notion-Version": _VERSION, "Content-Type": "application/json"}


def _check(r: httpx.Response) -> dict[str, Any]:
    if r.status_code == 401:
        raise ConnectorError("invalid Notion token", code="invalid_token", status=400)
    if r.status_code >= 400:
        raise ConnectorError(f"Notion HTTP {r.status_code}", code="notion_error", status=502)
    return r.json()


async def _get(token: str, path: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"{_API}{path}", headers=_auth(token))
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Notion unreachable: {exc}", code="network", status=502) from exc
    return _check(r)


async def _post(token: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(f"{_API}{path}", headers=_auth(token), json=body)
    except httpx.HTTPError as exc:
        raise ConnectorError(f"Notion unreachable: {exc}", code="network", status=502) from exc
    return _check(r)


def _page_title(props: dict[str, Any]) -> str:
    for p in props.values():
        if isinstance(p, dict) and p.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in (p.get("title") or [])).strip()
    return ""


def _is_done(props: dict[str, Any]) -> bool:
    """True if any status/select/checkbox property marks the page complete."""
    for name, p in props.items():
        if not isinstance(p, dict):
            continue
        t = p.get("type")
        if t == "status" and isinstance(p.get("status"), dict):
            if str(p["status"].get("name", "")).strip().lower() in _DONE:
                return True
        elif t == "select" and isinstance(p.get("select"), dict):
            if str(p["select"].get("name", "")).strip().lower() in _DONE:
                return True
        elif t == "checkbox" and p.get("checkbox") is True:
            if any(h in str(name).strip().lower() for h in _DONE_PROP_HINTS):
                return True
    return False


class NotionConnector(Connector):
    provider = "notion"
    kind = "tasks"

    async def verify_token(self, token: str, account: str | None = None) -> dict[str, Any]:
        me = await _get(token, "/v1/users/me")
        bot = me.get("bot") or {}
        workspace = bot.get("workspace_name") or me.get("name") or "notion"
        return {"external_account": workspace, "notion_bot_id": me.get("id")}

    async def sync(self, uid: str, conn: dict[str, Any], token: str) -> dict[str, Any]:
        data = await _post(token, "/v1/search",
                           {"filter": {"property": "object", "value": "page"}, "page_size": 100})
        pages = data.get("results", []) or []

        existing = await db_select("commitments", filters={"org_id": uid, "source": "notion"}, limit=5000)
        by_ext = {r.get("external_id"): r for r in existing if r.get("external_id")}

        added = updated = closed = 0
        for pg in pages:
            ext = str(pg.get("id") or "")
            if not ext:
                continue
            props = pg.get("properties") or {}
            title = _page_title(props) or "(untitled Notion page)"
            done = bool(pg.get("archived")) or _is_done(props)
            row = by_ext.get(ext)

            if row:
                cur = (row.get("status") or "open")
                if done and cur == "open":
                    await db_update("commitments", {"status": "done"},
                                    filters={"id": row["id"], "org_id": uid})
                    closed += 1
                elif not done and row.get("text") != title[:500]:
                    await db_update("commitments", {"text": title[:500]},
                                    filters={"id": row["id"], "org_id": uid})
                    updated += 1
                continue

            if done:
                continue  # already-done page we've never seen — don't resurrect it
            if await db_insert("commitments", {
                "org_id": uid, "text": title[:500], "kind": "action", "status": "open",
                "source": "notion", "external_id": ext,
            }):
                added += 1

        open_now = sum(1 for r in (existing) if (r.get("status") or "open") == "open") + added - closed
        return {
            "metadata": {"pages_seen": len(pages), "added": added, "updated": updated, "closed": closed},
            "added": added, "updated": updated, "closed": closed, "open": open_now,
        }


register(NotionConnector())
