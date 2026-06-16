"""AI avatar presence for the live Meeting Room — Tavus (primary) + Beyond
Presence (fallback).

Python port of the VIGIL meeting-room avatar chain (avatarSessions.js +
tavusClient.js + beyondPresenceClient.js). The agent joins a live room as a
video+voice avatar acting as the user's chosen advisor persona (CFO/CTO/COO/
CRM/CRO…), grounded in the user's uploaded documents. Tavus CVI is tried first;
on a config/auth/quota failure it falls back to Beyond Presence (LiveKit
transport).

All credentials come from the environment — nothing is hardcoded:
    TAVUS_API_KEY / TAVUS_SECONDARY_API_KEY, TAVUS_REPLICA_ID, TAVUS_PERSONA_ID,
    TAVUS_BASE_URL (default https://tavusapi.com), TAVUS_DEFAULT_LANGUAGE
    BEYOND_PRESENCE_API_KEY, BEYOND_PRESENCE_AVATAR_ID, BEYOND_PRESENCE_BASE_URL,
    BEYOND_PRESENCE_DEFAULT_LANGUAGE
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

from winny_gateway.logging import get_logger

logger = get_logger(__name__)

_TAVUS_FALLBACK_STATUSES = {401, 402, 403, 429}


# ── config / status ─────────────────────────────────────────────────────────
def _tavus_base() -> str:
    return (os.getenv("TAVUS_BASE_URL") or "https://tavusapi.com").rstrip("/")


def _beyond_base() -> str:
    return (os.getenv("BEYOND_PRESENCE_BASE_URL") or "https://api.bey.dev").rstrip("/")


def tavus_status() -> dict[str, Any]:
    missing = []
    if not (os.getenv("TAVUS_API_KEY") or os.getenv("TAVUS_SECONDARY_API_KEY")):
        missing.append("TAVUS_API_KEY")
    if not os.getenv("TAVUS_REPLICA_ID"):
        missing.append("TAVUS_REPLICA_ID")
    return {
        "provider": "tavus",
        "configured": not missing,
        "missing": missing,
        "has_persona_id": bool(os.getenv("TAVUS_PERSONA_ID")),
        "base_url": _tavus_base(),
        "default_language": os.getenv("TAVUS_DEFAULT_LANGUAGE") or "french",
    }


def beyond_status() -> dict[str, Any]:
    missing = []
    if not os.getenv("BEYOND_PRESENCE_API_KEY"):
        missing.append("BEYOND_PRESENCE_API_KEY")
    if not os.getenv("BEYOND_PRESENCE_AVATAR_ID"):
        missing.append("BEYOND_PRESENCE_AVATAR_ID")
    return {"provider": "beyond_presence", "configured": not missing, "missing": missing, "base_url": _beyond_base()}


def avatar_status() -> dict[str, Any]:
    return {
        "ok": True,
        "provider_order": ["tavus", "beyond_presence"],
        "tavus": tavus_status(),
        "beyond_presence": beyond_status(),
    }


# ── persona context (the system grounding for the avatar) ───────────────────
def build_context(*, persona: str, topic: str, advisors: list[str] | None = None,
                   evidence: str | None = None, language: str = "french", extra: str | None = None) -> str:
    lines = [
        f"You are the user's AI {persona} presence in a live meeting, on their behalf.",
        f"Respond in {language} by default; adapt if a participant explicitly asks for another language.",
        "You are NOT the human owner and must never claim to be human.",
        "Help the host with short, professional, fact-grounded, useful interventions.",
        "For confidential, legal, financial, or infrastructure topics, never expose secrets; "
        "ask the owner's permission when needed.",
        f"Meeting topic: {topic or 'unspecified'}.",
    ]
    if advisors:
        lines.append(f"Available advisor lenses: {', '.join(advisors)}.")
    if evidence:
        lines.append(
            "Ground every claim in the user's uploaded source documents below — quote/cite them, "
            f"do not invent facts beyond them:\n<<<\n{evidence[:6000]}\n>>>"
        )
    if extra:
        lines.append(f"Additional context: {extra}")
    return "\n".join(lines)


# ── Tavus ───────────────────────────────────────────────────────────────────
def _tavus_keys() -> list[str]:
    return [k for k in (os.getenv("TAVUS_API_KEY"), os.getenv("TAVUS_SECONDARY_API_KEY")) if k]


async def _tavus_request(path: str, *, method: str = "GET", body: dict | None = None) -> dict[str, Any]:
    keys = _tavus_keys()
    if not keys:
        raise RuntimeError("tavus_not_configured: TAVUS_API_KEY")
    last: Exception | None = None
    async with httpx.AsyncClient(timeout=20.0) as client:
        for i, key in enumerate(keys):
            resp = await client.request(method, f"{_tavus_base()}{path}",
                                        headers={"x-api-key": key, "Content-Type": "application/json"},
                                        json=body)
            if resp.is_success:
                try:
                    return resp.json()
                except Exception:  # noqa: BLE001
                    return {"raw": resp.text}
            last = RuntimeError(f"tavus_{resp.status_code}: {resp.text[:200]}")
            if i < len(keys) - 1 and resp.status_code in _TAVUS_FALLBACK_STATUSES:
                logger.warning("tavus.retry_secondary_key status=%s", resp.status_code)
                continue
            break
    raise last or RuntimeError("tavus_request_failed")


async def create_tavus_conversation(*, name: str, context: str, greeting: str | None = None,
                                    language: str = "french", max_duration: int = 7200,
                                    persona_id: str | None = None, replica_id: str | None = None,
                                    audio_only: bool | None = None, callback_url: str | None = None) -> dict[str, Any]:
    """POST /v2/conversations — returns the Tavus CVI conversation (embeddable URL)."""
    properties: dict[str, Any] = {
        "max_call_duration": int(max_duration),
        "participant_left_timeout": 120,
        "language": language,
    }
    if audio_only is not None:
        properties["audio_only"] = audio_only
    body: dict[str, Any] = {
        "replica_id": replica_id or os.getenv("TAVUS_REPLICA_ID"),
        "conversation_name": name,
        "conversational_context": context,
        "properties": properties,
    }
    pid = persona_id or os.getenv("TAVUS_PERSONA_ID")
    if pid:
        body["persona_id"] = pid
    if greeting:
        body["custom_greeting"] = greeting
    cb = callback_url or os.getenv("TAVUS_CALLBACK_URL")
    if cb:
        body["callback_url"] = cb
    return await _tavus_request("/v2/conversations", method="POST", body=body)


async def end_tavus_conversation(conversation_id: str) -> None:
    try:
        await _tavus_request(f"/v2/conversations/{conversation_id}/end", method="POST")
    except Exception as exc:  # noqa: BLE001
        logger.warning("tavus.end_failed id=%s: %s", conversation_id, exc)


# ── Beyond Presence (fallback) ──────────────────────────────────────────────
async def create_beyond_agent(*, name: str, context: str, greeting: str | None = None,
                              language: str = "fr", avatar_id: str | None = None) -> dict[str, Any]:
    """POST /v1/agents — Beyond Presence video agent (LiveKit transport)."""
    key = os.getenv("BEYOND_PRESENCE_API_KEY")
    if not key:
        raise RuntimeError("beyond_not_configured: BEYOND_PRESENCE_API_KEY")
    body = {
        "avatar_id": avatar_id or os.getenv("BEYOND_PRESENCE_AVATAR_ID"),
        "name": name,
        "system_prompt": context,
        "greeting": greeting or "",
        "language": language or os.getenv("BEYOND_PRESENCE_DEFAULT_LANGUAGE") or "fr",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{_beyond_base()}/v1/agents",
                                 headers={"x-api-key": key, "Content-Type": "application/json"}, json=body)
        resp.raise_for_status()
        return resp.json()


# ── the chain ───────────────────────────────────────────────────────────────
async def create_avatar_session(*, room_id: str, persona: str, topic: str,
                                advisors: list[str] | None = None, evidence: str | None = None,
                                language: str | None = None, greeting: str | None = None) -> dict[str, Any]:
    """Try Tavus → Beyond Presence. Returns a normalized session dict with the
    join URL the frontend embeds, or raises if neither provider is configured."""
    errors: list[dict[str, Any]] = []
    name = f"VIGIL · {persona} · {topic or room_id}"[:80]

    ts = tavus_status()
    if ts["configured"]:
        ctx = build_context(persona=persona, topic=topic, advisors=advisors, evidence=evidence,
                            language=language or ts["default_language"])
        try:
            sess = await create_tavus_conversation(name=name, context=ctx, greeting=greeting,
                                                   language=language or ts["default_language"])
            return _normalize("tavus", sess, room_id, persona, errors)
        except Exception as exc:  # noqa: BLE001
            errors.append({"provider": "tavus", "error": str(exc)})
    else:
        errors.append({"provider": "tavus", "skipped": True, "missing": ts["missing"]})

    bs = beyond_status()
    if bs["configured"]:
        ctx = build_context(persona=persona, topic=topic, advisors=advisors, evidence=evidence,
                            language=language or "fr")
        try:
            sess = await create_beyond_agent(name=name, context=ctx, greeting=greeting, language=language or "fr")
            return _normalize("beyond_presence", sess, room_id, persona, errors)
        except Exception as exc:  # noqa: BLE001
            errors.append({"provider": "beyond_presence", "error": str(exc)})
    else:
        errors.append({"provider": "beyond_presence", "skipped": True, "missing": bs["missing"]})

    raise RuntimeError(f"no_avatar_provider_available: {errors}")


def _normalize(provider: str, sess: dict[str, Any], room_id: str, persona: str, errors: list) -> dict[str, Any]:
    sid = sess.get("conversation_id") or sess.get("session_id") or sess.get("id")
    return {
        "ok": True,
        "provider": provider,
        "provider_session_id": sid,
        "room_id": room_id,
        "persona": persona,
        "conversation_id": sess.get("conversation_id") or sid,
        "conversation_url": sess.get("conversation_url") or sess.get("session_url") or sess.get("livekit_url"),
        "livekit_url": sess.get("livekit_url"),
        "status": sess.get("status") or "active",
        "fallback_chain": errors,
        "created_at": datetime.now(UTC).isoformat(),
    }
