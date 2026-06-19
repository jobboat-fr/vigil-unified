"""Auto-advisor — the "brain loop" that lets the Meet bot converse on its own.

While the bot is in a call it scrapes captions into a transcript. This module
watches that transcript and, on a cadence, asks the council's LLM (the HF
Inference Router — same brain the VIGIL council uses) whether the advisor
should speak now and, if so, what to say. A contribution is appended to the
bot's say-queue, which the realtime speaker voices via ElevenLabs.

Guardrails keep it from being annoying:
  * cadence — at least ``min_gap`` seconds between spoken interventions;
  * only react to NEW conversation since the last look;
  * the model is told to PASS most of the time and keep replies to one
    short, natural sentence grounded in the evidence.

Self-contained (stdlib urllib) so it runs inside the bot subprocess on OVH
without importing the gateway's council package. The decision + wording still
come from the same HF model the council uses; wiring the full intervention
engine (specialist fan-out → judge) via the gateway is a later upgrade.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable, Optional

_HF_URL = "https://router.huggingface.co/v1/chat/completions"
_DEFAULT_MODEL = "openai/gpt-oss-20b"  # fast reviewer-class model for low latency

_PERSONA_ROLE = {
    "CFO": "the Chief Financial Officer (finance, ROI, runway, burn, risk)",
    "CTO": "the Chief Technology Officer (architecture, security, delivery)",
    "COO": "the Chief Operating Officer (operations, process, execution)",
    "CRM": "the head of CRM (pipeline, relationships, follow-ups)",
    "CRO": "the Chief Revenue Officer (sales, growth, deals)",
    "advisor": "a trusted advisor",
}


def _build_messages(persona: str, topic: str, evidence: str, transcript: str) -> list:
    role = _PERSONA_ROLE.get(persona, _PERSONA_ROLE["advisor"])
    system = (
        f"You are {role}, attending a LIVE meeting as the user's AI advisor. "
        "You hear the conversation through a transcript. Speak ONLY when you can "
        "add genuine value — most of the time you should PASS and stay quiet. "
        "When you do speak, say ONE short, natural spoken sentence (no preamble, "
        "no 'as your CFO'). Ground every claim in the evidence below; never invent "
        "figures. Do not repeat what was already said."
    )
    if evidence:
        system += "\n\nEvidence (your source of truth):\n" + evidence[:4000]
    if topic:
        system += f"\n\nMeeting topic: {topic}"
    user = (
        "Recent conversation:\n"
        f"{transcript[-2500:]}\n\n"
        "Should you say something right now? If yes, output ONLY the sentence to "
        'say. If not, output exactly "PASS".'
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _ask_hf(messages: list, *, token: str, model: str, bill_to: str, timeout: float = 20.0) -> str:
    body = json.dumps(
        {"model": model, "messages": messages, "max_tokens": 90, "temperature": 0.4}
    ).encode("utf-8")
    headers = {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
    }
    if bill_to:
        headers["x-hf-bill-to"] = bill_to
    req = urllib.request.Request(_HF_URL, data=body, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data["choices"][0]["message"]["content"] or "").strip()


def _enqueue_say(queue_path: Path, text: str) -> None:
    entry = {"id": os.urandom(6).hex(), "text": text}
    with open(queue_path, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(entry) + "\n")


def run_auto_advisor(
    *,
    out_dir: Path,
    persona: str,
    topic: str,
    evidence: str,
    stop_flag: dict,
    is_in_call: Callable[[], bool],
    logger=None,
    min_gap: float = 28.0,
    poll: float = 8.0,
) -> None:
    """Blocking loop — run in a daemon thread. Returns when stop_flag is set."""
    token = (os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN") or "").strip()
    if not token:
        if logger:
            logger("auto-advisor: no HF_TOKEN — disabled")
        return
    model = os.environ.get("HERMES_MEET_ADVISOR_MODEL", _DEFAULT_MODEL)
    bill_to = os.environ.get("HF_BILL_TO", "azzetco")
    transcript_path = out_dir / "transcript.txt"
    queue_path = out_dir / "say_queue.jsonl"

    last_len = 0
    last_spoke = 0.0
    # Let the meeting warm up before the first possible intervention.
    grace_until = time.time() + 20.0

    while not stop_flag.get("stop"):
        time.sleep(poll)
        if stop_flag.get("stop"):
            break
        now = time.time()
        if not is_in_call() or now < grace_until or (now - last_spoke) < min_gap:
            continue
        try:
            transcript = transcript_path.read_text(encoding="utf-8") if transcript_path.exists() else ""
        except OSError:
            continue
        if len(transcript) <= last_len + 40:  # no meaningful new conversation
            continue
        last_len = len(transcript)
        try:
            reply = _ask_hf(
                _build_messages(persona, topic, evidence, transcript),
                token=token,
                model=model,
                bill_to=bill_to,
            )
        except Exception as exc:  # noqa: BLE001
            if logger:
                logger(f"auto-advisor: HF call failed: {exc}")
            continue
        cleaned = reply.strip().strip('"').strip()
        if not cleaned or cleaned.upper().startswith("PASS") or len(cleaned) < 4:
            continue
        _enqueue_say(queue_path, cleaned)
        last_spoke = time.time()
        if logger:
            logger(f"auto-advisor: spoke: {cleaned[:80]}")


def start_auto_advisor_thread(**kwargs) -> threading.Thread:
    t = threading.Thread(target=run_auto_advisor, kwargs=kwargs, name="meet-auto-advisor", daemon=True)
    t.start()
    return t
