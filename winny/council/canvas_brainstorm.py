"""Brainstorm-in-canvas — the agent thinks WITH you on the tldraw board.

Given the current board (the text of its blocks) and a prompt or a one-tap
"lens", the council returns a set of blocks to drop onto the canvas: ideas,
risks, gaps, next steps, multi-advisor takes, or a critique. Runs on the same
HF council as the rest; always returns *something* (degrades gracefully).
"""
from __future__ import annotations

from typing import Any

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny.council.summarizer import _parse_json

# lens -> (instruction, default kind/colour for the blocks it produces)
_LENSES: dict[str, tuple[str, str]] = {
    "ideas": ("Generate 4-6 fresh, concrete brainstorming ideas that build on the board.", "idea"),
    "expand": ("Expand the board (or the selection) into 4-6 sub-ideas, details, or considerations.", "idea"),
    "risks": ("Surface 3-5 real risks, blockers, or failure modes implied by the board.", "risk"),
    "missing": ("Point out 3-5 important things MISSING from the board — gaps, unasked questions.", "question"),
    "next_steps": ("Propose 3-5 concrete, owner-assignable next steps.", "action"),
    "critique": ("Play devil's advocate: 3-5 sharp counter-arguments against the board's direction.", "risk"),
    "summarize": ("Summarize the whole board into 2-4 crisp takeaways.", "note"),
    "council": (
        "Give each of these advisors ONE sharp take on the board, set the block's "
        "lens field to the role: CFO (finance/runway/ROI), CTO (architecture/risk/"
        "delivery), COO (operations/execution), CRO (revenue/growth). 4 blocks.",
        "note",
    ),
}

_KIND_COLOR = {"idea": "blue", "risk": "red", "question": "yellow", "action": "green", "note": "grey"}
_LENS_COLOR = {"CFO": "blue", "CTO": "violet", "COO": "orange", "CRO": "green"}

_SYSTEM = (
    "You are the VIGIL brainstorming partner working on a visual canvas with the "
    "user. {instruction}\n"
    "Each block must be ONE short phrase or sentence (canvas sticky-note sized) — "
    "no markdown, no numbering. Ground them in the board and prompt; never invent "
    "facts beyond them. Respond ONLY with JSON:\n"
    '{{"blocks":[{{"text":"...","kind":"idea|risk|question|action|note","lens":"optional role"}}]}}'
)


async def brainstorm_board(
    *, prompt: str = "", board_text: str = "", lens: str = "ideas", topic: str = ""
) -> dict[str, Any]:
    """Return {blocks:[{text,kind,color,lens}]} to place on the canvas."""
    instruction, default_kind = _LENSES.get(lens, _LENSES["ideas"])
    worker = worker_registry()["primary"]
    user = []
    if topic:
        user.append(f"Topic: {topic}")
    user.append("Current board:\n" + (board_text.strip()[:5000] or "(empty board)"))
    if prompt.strip():
        user.append(f"User's prompt: {prompt.strip()}")
    user.append("Produce the blocks. Respond ONLY with the JSON object.")

    try:
        result = await ask(
            worker,
            "\n\n".join(user),
            system=_SYSTEM.format(instruction=instruction),
            temperature=0.7,
            max_tokens=700,
        )
        parsed = _parse_json(result.get("output", "")) or {}
        stub = bool(result.get("stub", False))
    except Exception:  # noqa: BLE001
        parsed, stub = {}, False

    blocks: list[dict[str, Any]] = []
    for b in (parsed.get("blocks") or []):
        if not isinstance(b, dict):
            continue
        text = str(b.get("text") or "").strip()
        if not text:
            continue
        kind = str(b.get("kind") or default_kind).lower()
        role = str(b.get("lens") or "").strip().upper()
        color = _LENS_COLOR.get(role) or _KIND_COLOR.get(kind, "grey")
        blocks.append({"text": text[:240], "kind": kind, "color": color, "lens": role or None})

    return {"blocks": blocks[:8], "lens": lens, "stub": stub}
