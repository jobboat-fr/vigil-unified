"""Live intervention engine — "should the AI raise its hand right now?"

Python port of the VIGIL meeting-room `interventionCheck.js` + `behavioralOverlay.js`
(see docs/MEETING_ROOM_PORT_MAP.md). Called on a heartbeat (~12s) or after a
speaker change while a meeting is live. It behaves like a calm advisor in the
seat: it does NOT broadcast every thought — it raises its hand only when there's
a real signal, it's non-redundant with recent turns, and it's on-topic.

Algorithm:
  1. Load per-tenant behavioral weights (pattern_weights: cooldown_turns,
     min_specialist_signals, silence_bias).
  2. Cooldown guard — if the AI spoke within `cooldown_turns`, hold back.
  3. Fan out: each active specialty (CFO/CTO/Legal/Product) makes one brief
     observation in parallel (or "NOTHING TO FLAG").
  4. If fewer specialists fire than `min_specialist_signals`, skip the judge.
  5. Judge — decide speak/stay-silent, one-sentence message, urgency, reason.
  6. Behavioral overlay — veto low-urgency interventions when silence_bias is on.

Runs on the same HF-routed council workers as the rest of the system (ask()),
so it degrades to the deterministic stub when no LLM key is configured.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from winny.council.providers import ask
from winny.council.registry import worker_registry

# pattern_weights knobs (defaults match the original behavioralOverlay).
WEIGHT_DEFAULTS: dict[str, float] = {
    "cooldown_turns": 2.0,
    "min_specialist_signals": 1.0,
    "silence_bias": 0.0,
}

# specialty → which council worker voices it + its lens label.
SPECIALTIES: dict[str, dict[str, str]] = {
    "cfo": {"worker": "primary", "name": "finance & ROI"},
    "cto": {"worker": "reviewer_1", "name": "technology & architecture"},
    "legal": {"worker": "reviewer_2", "name": "legal & compliance"},
    "product": {"worker": "primary", "name": "product & UX"},
}

# Names that count as the AI's own turns in the transcript (for the cooldown).
_AI_SPEAKERS = {"vigil", "ai", "council", "advisor", "assistant"}

_JUDGE_SYSTEM = (
    "You are the single voice of the user's AI advisor, seated in a live meeting "
    "with other humans. You must NOT interrupt. You speak only when you have "
    "something clear, useful, and non-redundant to say.\n\n"
    "STRICT criteria to intervene:\n"
    "1. There is a concrete signal (risk, opportunity, omitted fact, contradiction).\n"
    "2. It was not already said in the last 5 turns.\n"
    "3. It adds immediate value to the conversation in progress.\n"
    "4. You can state it in ONE clear sentence (max 30 words).\n\n"
    "If none are met, do not intervene. Respond ONLY with strict JSON (no markdown):\n"
    '{"speak": true|false, "message": "one sentence if speak else empty", '
    '"urgency": "low"|"normal"|"high", "reason": "one short sentence", '
    '"touched_specialties": ["cfo"|"cto"|"legal"|"product"]}\n'
    "No emojis. Professional, collegial tone."
)


def _specialty_system(name: str) -> str:
    return (
        f"You are the {name} advisor silently listening to a live meeting. Produce ONE "
        f"relevant observation about what was just said, from the {name} angle, in 1-2 "
        'sentences max. If you have nothing useful to add, write exactly "NOTHING TO FLAG". '
        "No emojis."
    )


def _kind(speaker: str | None) -> str:
    return "ai" if str(speaker or "").strip().lower() in _AI_SPEAKERS else "human"


def apply_overlay(decision: dict[str, Any], weights: dict[str, float]) -> dict[str, Any]:
    """Post-judge veto based on tenant weights (ports behavioralOverlay.applyOverlay)."""
    if not decision.get("speak"):
        return decision
    if weights.get("silence_bias", 0) >= 1 and decision.get("urgency") == "low":
        return {
            "speak": False,
            "reason": "behavioral_overlay:low_urgency_vetoed",
            "message": "",
            "urgency": "low",
            "touched_specialties": decision.get("touched_specialties", []),
            "weights_applied": True,
        }
    return {**decision, "weights_applied": True}


async def check_intervention(
    *,
    transcript: list[dict[str, Any]],
    topic: str = "",
    weights: dict[str, float] | None = None,
    active_specialties: list[str] | None = None,
    window_size: int = 20,
) -> dict[str, Any]:
    """Decide whether the AI should raise its hand. `transcript` is a list of
    ``{speaker, text, ts}`` (oldest-first); `weights` comes from pattern_weights
    (defaults applied when absent)."""
    w = {**WEIGHT_DEFAULTS, **(weights or {})}
    specialties = active_specialties or ["cfo", "cto", "legal"]

    window = [u for u in transcript if u.get("text")][-window_size:]
    if not window:
        return {"speak": False, "reason": "transcript_empty"}

    # Cooldown guard — if the AI spoke within cooldown_turns, hold back.
    cooldown = max(1, round(w["cooldown_turns"]))
    if any(_kind(u.get("speaker")) == "ai" for u in window[-(cooldown + 1):]):
        return {"speak": False, "reason": "just_spoke_recently"}

    transcript_text = "\n".join(f"{u.get('speaker')}: {u.get('text')}" for u in window)
    registry = worker_registry()

    async def _observe(s: str) -> dict[str, str]:
        cfg = SPECIALTIES.get(s)
        if not cfg:
            return {"specialty": s, "observation": "NOTHING TO FLAG"}
        worker = registry.get(cfg["worker"]) or registry["primary"]
        prompt = (
            f"Meeting topic: {topic or 'unspecified'}\n\n"
            f"Recent transcript:\n{transcript_text}\n\n"
            f"{cfg['name']} observation (1-2 sentences or \"NOTHING TO FLAG\"):"
        )
        resp = await ask(worker, prompt, system=_specialty_system(cfg["name"]), temperature=0.3, max_tokens=120)
        return {"specialty": s, "observation": (resp.get("output") or "").strip()}

    results = await asyncio.gather(*[_observe(s) for s in specialties if s in SPECIALTIES], return_exceptions=True)
    observations = [
        r for r in results
        if isinstance(r, dict) and "nothing to flag" not in r["observation"].lower() and r["observation"]
    ]

    min_signals = max(1, round(w["min_specialist_signals"]))
    if len(observations) < min_signals:
        return {"speak": False, "reason": "no_specialist_signal"}

    judge = registry.get("chairman") or registry.get("reviewer_2") or registry["primary"]
    obs_block = "\n".join(f"[{o['specialty'].upper()}] {o['observation']}" for o in observations)
    judge_prompt = (
        f"Topic: {topic or 'unspecified'}\n\n"
        f"Recent transcript:\n{transcript_text}\n\n"
        f"Parallel observations from your advisors:\n{obs_block}\n\n"
        "Decide: intervene or not. Respond with strict JSON."
    )
    resp = await ask(judge, judge_prompt, system=_JUDGE_SYSTEM, temperature=0.2, max_tokens=250)
    parsed = _parse_json(resp.get("output", ""))
    if parsed is None:
        return {"speak": False, "reason": "judge_parse_failed"}

    decision = {
        "speak": bool(parsed.get("speak")),
        "message": str(parsed.get("message") or "").strip() if parsed.get("speak") else "",
        "urgency": parsed["urgency"] if parsed.get("urgency") in ("low", "normal", "high") else "normal",
        "reason": str(parsed.get("reason") or ""),
        "touched_specialties": [s for s in (parsed.get("touched_specialties") or []) if isinstance(s, str)]
        or [o["specialty"] for o in observations],
        "cost_usd": round(float(resp.get("cost_usd") or 0), 6),
        "stub": bool(resp.get("stub", False)),
    }
    return apply_overlay(decision, w)


def _parse_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                return None
    return None
