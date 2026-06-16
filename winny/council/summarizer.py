"""Post-meeting summarizer — Python port of the VIGIL meetingSummarizer +
postMeetingPipeline.

Turns a finished meeting transcript into a structured close: a Markdown summary,
the decisions, the commitments (action items), next steps, and follow-ups for
guests to onboard. Runs on the HF-routed council (ask()), degrading to a
deterministic stub when no key is set.
"""

from __future__ import annotations

import json
from typing import Any

from winny.council.providers import ask
from winny.council.registry import worker_registry

_SYSTEM = (
    "You are the VIGIL meeting scribe. Given a meeting transcript, produce a tight, "
    "accurate close — no invention, only what the transcript supports. Respond ONLY "
    "with a JSON object matching exactly:\n"
    '{"summary_markdown": "a concise Markdown recap (## headings)",'
    ' "decisions": ["..."],'
    ' "commitments": [{"text": "the action item", "owner": "who", "due": "when or empty"}],'
    ' "next_steps": ["..."],'
    ' "follow_ups": [{"name": "guest/contact name", "company": "", "next_step": "the follow-up to take"}]}'
)


async def summarize_meeting(*, transcript_text: str, topic: str = "") -> dict[str, Any]:
    """Returns {summary_markdown, decisions, commitments, next_steps, follow_ups, stub}."""
    if not transcript_text.strip():
        return {"summary_markdown": "", "decisions": [], "commitments": [], "next_steps": [], "follow_ups": [], "stub": False, "empty": True}
    worker = worker_registry()["primary"]
    prompt = (
        f"Meeting topic: {topic or 'unspecified'}\n\n"
        f"Transcript:\n{transcript_text[:16000]}\n\n"
        "Produce the close. Respond ONLY with the JSON object."
    )
    result = await ask(worker, prompt, system=_SYSTEM, temperature=0.3, max_tokens=1800)
    parsed = _parse_json(result.get("output", "")) or {}
    return {
        "summary_markdown": str(parsed.get("summary_markdown") or ""),
        "decisions": [d for d in (parsed.get("decisions") or []) if isinstance(d, str)],
        "commitments": [c for c in (parsed.get("commitments") or []) if isinstance(c, dict)],
        "next_steps": [s for s in (parsed.get("next_steps") or []) if isinstance(s, str)],
        "follow_ups": [f for f in (parsed.get("follow_ups") or []) if isinstance(f, dict)],
        "stub": bool(result.get("stub", False)),
    }


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
