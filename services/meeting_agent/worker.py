"""AZZMIN en salle — l'agent qui REJOINT une salle LiveKit comme participant réel.

Worker livekit-agents (1.8.x), enregistré sous le nom `vigil-advisor`. La passerelle
l'envoie dans la salle `vigil-{room_id}` quand l'animateur clique « Faire entrer AZZMIN »
(POST /v1/rooms/{id}/bring-agent), avec {persona, topic, evidence, room_id, owner_id,
host_identity, kind}.

Il se comporte comme un participant humain attentif : il écoute, et ne parle que quand
l'algorithme d'intervention existant le décide. Aucune logique de décision ici — elle vit
dans la passerelle et reste celle déjà en place :

  1. chaque tour de parole entendu est ajouté au fil de la séance
     (POST /v1/rooms/{id}/messages) ;
  2. la passerelle décide (POST /v1/rooms/{id}/intervention-check : spécialistes → juge →
     surcouche comportementale, poids pattern_weights, journal ai_interventions) ;
  3. speak=false → silence (StopResponse) ; speak=true → AZZMIN dit decision.message, et
     cette intervention est à son tour écrite au fil (ce qui alimente le délai de retenue).

Panne de la passerelle ou de l'IA : silence. L'agent ne parle jamais « par défaut ».

Écoute : LiveKit relie la session à un participant à la fois. L'agent suit la parole : il
se relie au participant qui parle (événement active_speakers_changed), en commençant par
l'animateur.

Voix : ElevenLabs si VIGIL_TTS=elevenlabs et une clé est fournie, sinon la synthèse
LiveKit Inference (VIGIL_TTS_MODEL, Cartesia sonic-3 en français par défaut), facturée au
projet LiveKit — aucune autre clé nécessaire.
Visage : Beyond Presence (BEY_API_KEY ou BEYOND_PRESENCE_API_KEY, avatar
BEYOND_PRESENCE_AVATAR_ID) par défaut, Tavus en secours, voix seule si les deux échouent.

Lancer :  python worker.py start          (production)
          python worker.py download-files (modèle VAD, au déploiement)

Env : LIVEKIT_URL/API_KEY/API_SECRET, GROQ_API_KEY (écoute), VTLVS_GATEWAY_URL,
      WW_SERVICE_TOKEN, et les clés de voix/visage ci-dessus.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    RoomInputOptions,
    RoomOutputOptions,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.llm import StopResponse
from livekit.plugins import groq, silero

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("azzmin-salle")

AGENT_NAME = "AZZMIN"
GATEWAY_TIMEOUT_S = float(os.getenv("VIGIL_AGENT_GATEWAY_TIMEOUT_S", "25"))

PERSONA = {
    "AZZMIN": "AZZMIN, l'agent d'AZZ&CO Labs qui assiste la séance",
    "CFO": "le directeur financier de l'organisme (finances, budget, risques)",
    "CTO": "le directeur technique de l'organisme (architecture, sécurité, livraison)",
    "COO": "le directeur des opérations (organisation, process, exécution)",
    "CRM": "le responsable relation client (suivi, relances)",
    "CRO": "le responsable commercial (ventes, développement)",
    "advisor": "un conseiller de confiance",
}


def build_instructions(persona: str, topic: str, evidence: str, kind: str) -> str:
    role = PERSONA.get(persona, PERSONA["AZZMIN"])
    cadre = (
        "une séance de formation à distance, avec un formateur et des apprenants"
        if kind == "formation"
        else "une réunion en direct"
    )
    parts = [
        f"Tu es {role}, présent dans {cadre}.",
        "Tu es une IA et tu ne prétends jamais être humain. Tu parles français, au vouvoiement,"
        " en une ou deux phrases. Tu ne coupes jamais la parole et tu n'interviens que si tu"
        " apportes quelque chose d'utile.",
        "En formation, tu soutiens le formateur : tu ne donnes pas les réponses d'une évaluation"
        " et tu ne signes ni n'attestes rien.",
        "Tu t'appuies sur les documents fournis ; tu n'inventes aucun chiffre. Si tu ne sais pas,"
        " tu le dis.",
        f"Sujet : {topic or 'non précisé'}.",
    ]
    if evidence:
        parts.append("Documents de référence :\n" + evidence[:4000])
    return "\n".join(parts)


class Passerelle:
    """Les deux appels à la passerelle, au nom du propriétaire de la salle."""

    def __init__(self, room_id: str, owner_id: str) -> None:
        self.room_id = room_id
        base = (os.getenv("VTLVS_GATEWAY_URL") or "https://app.vtlvs.com").rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=base,
            timeout=GATEWAY_TIMEOUT_S,
            headers={
                "Authorization": f"Bearer {os.getenv('WW_SERVICE_TOKEN', '')}",
                "X-WinnyWoo-User-Id": owner_id,
                "content-type": "application/json",
            },
        )

    async def ajouter(self, speaker: str, text: str) -> None:
        r = await self._client.post(f"/v1/rooms/{self.room_id}/messages", json={"speaker": speaker, "text": text})
        r.raise_for_status()

    async def decider(self, topic: str) -> dict[str, Any]:
        r = await self._client.post(f"/v1/rooms/{self.room_id}/intervention-check", json={"topic": topic})
        r.raise_for_status()
        return (r.json() or {}).get("data") or {}

    async def fermer(self) -> None:
        await self._client.aclose()


class AgentDeSalle(Agent):
    """Écoute, écrit au fil, demande à l'algorithme, se tait ou parle — rien d'autre."""

    def __init__(self, *, instructions: str, passerelle: Passerelle, topic: str, noms: dict[str, str]) -> None:
        super().__init__(instructions=instructions)
        self._passerelle = passerelle
        self._topic = topic
        self._noms = noms  # identité LiveKit → nom affiché
        self.orateur: str | None = None

    async def on_user_turn_completed(self, turn_ctx: llm.ChatContext, new_message: llm.ChatMessage) -> None:
        text = (new_message.text_content or "").strip()
        if not text:
            raise StopResponse()
        speaker = self._noms.get(self.orateur or "", "Participant")
        try:
            await self._passerelle.ajouter(speaker, text)
            decision = await self._passerelle.decider(self._topic)
        except Exception as exc:  # noqa: BLE001 — passerelle ou IA en panne : silence
            logger.warning("intervention indisponible, silence : %s", exc)
            raise StopResponse() from exc

        message = str(decision.get("message") or "").strip()
        if not decision.get("speak") or not message:
            logger.info("silence (%s)", decision.get("reason"))
            raise StopResponse()

        logger.info("intervention (%s) : %s", decision.get("urgency"), message[:120])
        self.session.say(message, allow_interruptions=True, add_to_chat_ctx=True)
        try:
            await self._passerelle.ajouter(AGENT_NAME, message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("intervention non écrite au fil : %s", exc)
        raise StopResponse()


def choisir_voix():
    """ElevenLabs si demandé et configuré ; sinon la synthèse LiveKit Inference."""
    el_key = os.getenv("ELEVENLABS_API_KEY") or os.getenv("ELEVEN_API_KEY")
    if os.getenv("VIGIL_TTS", "inference").lower() == "elevenlabs" and el_key:
        from livekit.plugins import elevenlabs

        return elevenlabs.TTS(
            voice_id=os.getenv("ELEVENLABS_VOICE_ID", "pFZP5JQG7iQjIQuC4Bku"),
            model=os.getenv("ELEVENLABS_MODEL", "eleven_flash_v2_5"),
            api_key=el_key,
            language="fr",
        )
    from livekit.agents import inference

    kwargs: dict[str, Any] = {"model": os.getenv("VIGIL_TTS_MODEL", "cartesia/sonic-3"), "language": "fr"}
    if os.getenv("VIGIL_TTS_VOICE"):
        kwargs["voice"] = os.getenv("VIGIL_TTS_VOICE")
    return inference.TTS(**kwargs)


async def demarrer_avatar(session: AgentSession, room: rtc.Room) -> bool:
    """Beyond Presence, puis Tavus. Vrai si un avatar publie l'audio et la vidéo."""
    if os.getenv("VIGIL_AGENT_AVATAR", "1").lower() in ("0", "false", "off"):
        return False
    bey_key = os.getenv("BEY_API_KEY") or os.getenv("BEYOND_PRESENCE_API_KEY")
    if bey_key:
        try:
            from livekit.plugins import bey

            kwargs: dict[str, Any] = {"api_key": bey_key, "avatar_participant_name": AGENT_NAME}
            if os.getenv("BEYOND_PRESENCE_AVATAR_ID"):
                kwargs["avatar_id"] = os.getenv("BEYOND_PRESENCE_AVATAR_ID")
            await bey.AvatarSession(**kwargs).start(session, room=room)
            logger.info("avatar Beyond Presence démarré")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Beyond Presence indisponible : %s", exc)
    if os.getenv("TAVUS_API_KEY") and os.getenv("TAVUS_REPLICA_ID"):
        try:
            from livekit.plugins import tavus

            kwargs = {
                "replica_id": os.getenv("TAVUS_REPLICA_ID"),
                "api_key": os.getenv("TAVUS_API_KEY"),
                "avatar_participant_name": AGENT_NAME,
            }
            if os.getenv("TAVUS_PERSONA_ID"):
                kwargs["persona_id"] = os.getenv("TAVUS_PERSONA_ID")
            await tavus.AvatarSession(**kwargs).start(session, room=room)
            logger.info("avatar Tavus démarré")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tavus indisponible, voix seule : %s", exc)
    return False


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    meta: dict[str, Any] = {}
    try:
        meta = json.loads(ctx.job.metadata or "{}")
    except Exception:  # noqa: BLE001
        pass
    persona = meta.get("persona") or "AZZMIN"
    topic = meta.get("topic") or ""
    room_id = meta.get("room_id") or ctx.room.name.removeprefix("vigil-")
    owner_id = meta.get("owner_id") or ""
    host = meta.get("host_identity") or ""
    logger.info("AZZMIN rejoint room=%s persona=%s kind=%s", ctx.room.name, persona, meta.get("kind"))

    passerelle = Passerelle(room_id, owner_id)
    ctx.add_shutdown_callback(passerelle.fermer)
    noms: dict[str, str] = {}
    agent = AgentDeSalle(
        instructions=build_instructions(persona, topic, meta.get("evidence") or "", meta.get("kind") or ""),
        passerelle=passerelle,
        topic=topic,
        noms=noms,
    )

    session = AgentSession(
        stt=groq.STT(model=os.getenv("VIGIL_AGENT_STT", "whisper-large-v3-turbo"), language="fr"),
        llm=groq.LLM(model=os.getenv("VIGIL_AGENT_LLM", "llama-3.3-70b-versatile")),
        tts=choisir_voix(),
        vad=silero.VAD.load(),
    )

    avatar = await demarrer_avatar(session, ctx.room)

    input_kwargs: dict[str, Any] = {"close_on_disconnect": False}
    if host:
        input_kwargs["participant_identity"] = host
    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(**input_kwargs),
        room_output_options=RoomOutputOptions(audio_enabled=not avatar),
    )

    def nommer(p: rtc.RemoteParticipant) -> None:
        noms[p.identity] = p.name or p.identity

    for p in ctx.room.remote_participants.values():
        nommer(p)
    ctx.room.on("participant_connected", nommer)
    linked = session.room_io.linked_participant
    agent.orateur = linked.identity if linked else (host or None)

    # Suivre la parole : se relier à qui parle, jamais à soi-même ni à un autre agent (avatar).
    def on_speakers(speakers: list[rtc.Participant]) -> None:
        for sp in speakers:
            if sp.identity == ctx.room.local_participant.identity:
                continue
            if sp.kind == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT:
                continue
            if isinstance(sp, rtc.RemoteParticipant) and sp.identity != agent.orateur:
                session.room_io.set_participant(sp.identity)
                agent.orateur = sp.identity
            break

    ctx.room.on("active_speakers_changed", on_speakers)

    # Une phrase fixe : l'accueil ne dépend d'aucun modèle.
    session.say(
        "Bonjour, je suis AZZMIN. J'écoute la séance et j'interviendrai seulement si c'est utile.",
        allow_interruptions=True,
    )


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="vigil-advisor"))
