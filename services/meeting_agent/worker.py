"""VIGIL meeting agent — the AI model that JOINS a live LiveKit room as a real
participant (CFO/CTO/COO/CRM/CRO): hears the room, thinks, and speaks, with a
Tavus avatar face.

A livekit-agents worker (1.6.x). It registers with LiveKit under agent name
`vigil-advisor` and waits to be dispatched. The gateway dispatches it into room
`vigil-{room_id}` with metadata {persona, topic, evidence} when the host clicks
"Bring in AI". Pipeline: OpenAI Whisper (STT) → gpt-4o-mini with the persona
prompt grounded in the user's uploaded docs (LLM) → OpenAI TTS, rendered by a
Tavus avatar (falls back to voice-only if Tavus is unavailable).

Run:  python worker.py start        (production)
      python worker.py download-files  (prefetch the VAD model at build time)

Env: LIVEKIT_URL/API_KEY/API_SECRET, OPENAI_API_KEY, TAVUS_API_KEY,
     TAVUS_REPLICA_ID (+ optional TAVUS_PERSONA_ID), and tuning:
     VIGIL_AGENT_LLM (gpt-4o-mini), VIGIL_AGENT_VOICE (alloy),
     VIGIL_AGENT_AVATAR (1 to enable Tavus, 0 for voice-only).
"""

from __future__ import annotations

import json
import logging
import os

from livekit.agents import Agent, AgentSession, JobContext, RoomOutputOptions, WorkerOptions, cli
from livekit.plugins import elevenlabs, groq, silero

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vigil-agent")

PERSONA = {
    "CFO": "the user's Chief Financial Officer (finance, ROI, budget, runway, risk)",
    "CTO": "the user's Chief Technology Officer (architecture, security, delivery)",
    "COO": "the user's Chief Operating Officer (operations, process, execution)",
    "CRM": "the user's head of CRM (pipeline, relationships, follow-ups)",
    "CRO": "the user's Chief Revenue Officer (sales, growth, deals)",
    "advisor": "the user's trusted advisor",
}


def build_instructions(persona: str, topic: str, evidence: str) -> str:
    role = PERSONA.get(persona, PERSONA["advisor"])
    parts = [
        f"You are {role}, attending a LIVE meeting on the user's behalf with other people.",
        "You are an AI; never claim to be human. This is a real-time voice call — speak "
        "naturally and keep replies short (1-2 sentences). Only speak when you add value.",
        "Ground every claim in the user's uploaded documents below; never invent figures. "
        "If you don't know, say so and offer to check.",
        f"Meeting topic: {topic or 'unspecified'}.",
    ]
    if evidence:
        parts.append("Source documents to ground in:\n" + evidence[:4000])
    return "\n".join(parts)


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    meta: dict = {}
    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except Exception:  # noqa: BLE001
        pass
    persona = meta.get("persona", "advisor")
    instructions = build_instructions(persona, meta.get("topic", ""), meta.get("evidence", ""))
    logger.info("vigil-agent joining room=%s persona=%s", ctx.room.name, persona)

    # Brain + ears on Groq (fast, has quota); voice on ElevenLabs (reads
    # ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID — works once the real key is set).
    session = AgentSession(
        stt=groq.STT(model=os.getenv("VIGIL_AGENT_STT", "whisper-large-v3-turbo")),
        llm=groq.LLM(model=os.getenv("VIGIL_AGENT_LLM", "llama-3.3-70b-versatile")),
        tts=elevenlabs.TTS(voice_id=os.getenv("ELEVENLABS_VOICE_ID", "pFZP5JQG7iQjIQuC4Bku")),
        vad=silero.VAD.load(),
    )

    # Tavus avatar publishes the agent's face + voice into the room; otherwise the
    # agent is voice-only (still a real participant). Either way it's IN the call.
    output = RoomOutputOptions(audio_enabled=True)
    if os.getenv("TAVUS_API_KEY") and os.getenv("VIGIL_AGENT_AVATAR", "1").lower() not in ("0", "false", "off"):
        try:
            from livekit.plugins import tavus

            avatar = tavus.AvatarSession(
                replica_id=os.getenv("TAVUS_REPLICA_ID"),
                persona_id=os.getenv("TAVUS_PERSONA_ID") or None,
                api_key=os.getenv("TAVUS_API_KEY"),
                avatar_participant_name=f"VIGIL {persona}",
            )
            await avatar.start(session, room=ctx.room)
            output = RoomOutputOptions(audio_enabled=False)  # the avatar publishes the AV
            logger.info("tavus avatar started")
        except Exception as exc:  # noqa: BLE001
            logger.warning("tavus avatar unavailable, voice-only: %s", exc)

    await session.start(room=ctx.room, agent=Agent(instructions=instructions), room_output_options=output)
    await session.generate_reply(
        instructions=f"Greet everyone in ONE short sentence as their {persona}, then listen."
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="vigil-advisor"))
