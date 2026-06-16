"""Meeting-room tools for the Hermes agent.

Makes the VIGIL meeting room native to Hermes: the agent can deliberate with the
council, decide in real time whether to raise its hand, and spawn its own
video+voice avatar (Tavus → Beyond Presence) to act as the user's advisor
(CFO/CTO/COO/CRM/CRO) — grounded in the user's uploaded documents.

These wrap the in-process winny.council + winny_gateway.avatar modules (no HTTP
hop); the LLM runs on the same council the rest of the system uses, degrading to
a deterministic stub when no key is set. Pair with Hermes' own transcription
(STT), tts/voice, and memory tools — the meeting-room skill explains when.
See docs/MEETING_ROOM_PORT_MAP.md.
"""

from __future__ import annotations

import json
from typing import Any

from tools.registry import registry, tool_error

_LENSES = {"cfo_review", "tech_review", "legal_review", "product_review"}


def _parse_turns(transcript: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for line in str(transcript or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            speaker, text = line.split(":", 1)
            turns.append({"speaker": speaker.strip(), "text": text.strip()})
        else:
            turns.append({"speaker": "Participant", "text": line})
    return turns


async def _council_convene(args: dict[str, Any], **_kw) -> str:
    from winny.council import (
        REVIEWER_SYSTEM_PROMPT,
        ROLE_SYSTEM_PROMPTS,
        AIWorkerCollective,
    )

    lens = args.get("lens") or "cfo_review"
    if lens not in _LENSES:
        return tool_error(f"unknown lens '{lens}'. Use one of: {sorted(_LENSES)}")
    transcript = str(args.get("transcript") or "").strip()
    if not transcript:
        return tool_error("transcript is required")
    question = args.get("question")
    primary_user = transcript + (f"\n\nFocus question: {question}" if question else "")
    scenario = {
        "id": "hermes",
        "transcript": transcript,
        "primarySystemPrompt": ROLE_SYSTEM_PROMPTS.get(lens, ""),
        "primaryUserPrompt": (
            f"Meeting transcript:\n\n{primary_user}\n\n"
            "What is your intervention? Respond ONLY with the JSON object."
        ),
        "reviewerSystemPrompt": REVIEWER_SYSTEM_PROMPT,
    }
    try:
        record = await AIWorkerCollective().orchestrate(lens, scenario)
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"council failed: {exc}")
    v = record.get("verdict", {})
    fi = v.get("final_intervention", {}) or {}
    return json.dumps({
        "lens": lens,
        "readiness_pass": v.get("readiness_pass"),
        "readiness_score": v.get("readiness_score"),
        "consensus_reached": v.get("consensus_reached"),
        "should_intervene": fi.get("should_intervene"),
        "intervention": fi.get("intervention_text"),
        "reasoning": fi.get("reasoning"),
        "confidence": fi.get("confidence"),
        "cost_usd": record.get("totals", {}).get("cost_usd"),
    }, ensure_ascii=False, default=str)


async def _intervention_check(args: dict[str, Any], **_kw) -> str:
    from winny.council.intervention import check_intervention

    transcript = args.get("transcript")
    turns = transcript if isinstance(transcript, list) else _parse_turns(str(transcript or ""))
    if not turns:
        return tool_error("transcript is required")
    try:
        decision = await check_intervention(
            transcript=turns,
            topic=str(args.get("topic") or ""),
            active_specialties=args.get("specialties") or ["cfo", "cto", "legal"],
        )
    except Exception as exc:  # noqa: BLE001
        return tool_error(f"intervention check failed: {exc}")
    return json.dumps(decision, ensure_ascii=False, default=str)


async def _start_avatar(args: dict[str, Any], **_kw) -> str:
    from winny_gateway import avatar as avatar_mod

    try:
        session = await avatar_mod.create_avatar_session(
            room_id=str(args.get("room_id") or "hermes"),
            persona=str(args.get("persona") or "advisor"),
            topic=str(args.get("topic") or ""),
            evidence=args.get("evidence"),
            language=args.get("language"),
            greeting=args.get("greeting"),
        )
    except RuntimeError as exc:
        return tool_error(str(exc))
    return json.dumps({
        "provider": session.get("provider"),
        "conversation_url": session.get("conversation_url"),
        "conversation_id": session.get("conversation_id"),
        "persona": session.get("persona"),
    }, ensure_ascii=False, default=str)


COUNCIL_CONVENE_SCHEMA = {
    "name": "council_convene",
    "description": (
        "Convene the VIGIL AI council over a meeting transcript or decision and "
        "return a weighted verdict (primary advisor + two reviewers + chairman "
        "synthesis). Use for a deliberate decision review. For a fast live "
        "'should I speak now?' check use meeting_intervention_check instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "transcript": {"type": "string", "description": "Meeting transcript / decision context."},
            "lens": {"type": "string", "enum": sorted(_LENSES), "description": "Advisor lens."},
            "question": {"type": "string", "description": "Optional focus question."},
        },
        "required": ["transcript", "lens"],
    },
}

INTERVENTION_CHECK_SCHEMA = {
    "name": "meeting_intervention_check",
    "description": (
        "During a LIVE meeting, decide whether to raise the AI's hand right now. "
        "Specialist fan-out (CFO/CTO/Legal/Product) over the recent transcript "
        "then a judge. Returns {speak, message, urgency, reason}. Stays silent "
        "unless there's a real, non-redundant, on-topic signal — only surface "
        "message when speak=true. Build the transcript with the transcription "
        "tool (STT); speak the message with the tts/voice tools or the avatar."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "transcript": {"type": "string", "description": "Recent 'Speaker: text' lines, oldest first."},
            "topic": {"type": "string", "description": "Meeting topic."},
            "specialties": {"type": "array", "items": {"type": "string", "enum": ["cfo", "cto", "legal", "product"]}},
        },
        "required": ["transcript"],
    },
}

START_AVATAR_SCHEMA = {
    "name": "start_avatar",
    "description": (
        "Spawn the AI's video+voice avatar (Tavus, Beyond Presence fallback) to "
        "act as the user's advisor persona in a live meeting, grounded in the "
        "user's uploaded documents. Returns an embeddable conversation_url. Use "
        "when the user wants the AI to JOIN a meeting with face+voice; for "
        "text-only deliberation use council_convene / meeting_intervention_check."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "persona": {"type": "string", "description": "CFO | CTO | COO | CRM | CRO | advisor"},
            "topic": {"type": "string", "description": "Meeting topic."},
            "evidence": {"type": "string", "description": "Source documents to ground the avatar in."},
            "language": {"type": "string", "description": "e.g. 'french', 'english'."},
            "greeting": {"type": "string", "description": "Optional opening line."},
            "room_id": {"type": "string", "description": "Optional room id to tag the session."},
        },
        "required": ["persona"],
    },
}


registry.register(name="council_convene", toolset="meeting_room", schema=COUNCIL_CONVENE_SCHEMA, handler=_council_convene, is_async=True, emoji="⚖️")
registry.register(name="meeting_intervention_check", toolset="meeting_room", schema=INTERVENTION_CHECK_SCHEMA, handler=_intervention_check, is_async=True, emoji="✋")
registry.register(name="start_avatar", toolset="meeting_room", schema=START_AVATAR_SCHEMA, handler=_start_avatar, is_async=True, emoji="🎭")
