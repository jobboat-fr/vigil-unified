"""ElevenLabs speaker — a drop-in alternative to ``RealtimeSession`` that
synthesises ``meet_say`` text with ElevenLabs instead of OpenAI Realtime.

It exposes the same surface the meet bot and :class:`RealtimeSpeaker` rely on
(``connect`` / ``speak`` / ``close`` plus the ``audio_bytes_out`` /
``last_audio_out_at`` counters), so it slots in wherever ``RealtimeSession``
does — selected at runtime by ``HERMES_MEET_VOICE_PROVIDER=elevenlabs``.

ElevenLabs' ``output_format=pcm_24000`` returns raw 16-bit little-endian mono
PCM at 24 kHz — byte-identical to what OpenAI Realtime writes — so the audio
sink file and the ``paplay``/ffmpeg pump downstream need no changes.

Stdlib only (urllib) — no new dependency. The agent's brain still decides what
to say; this only changes the voice that says it.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Matches RealtimeSession's default and what the WinnyWoo meeting agent uses.
_DEFAULT_VOICE_ID = "pFZP5JQG7iQjIQuC4Bku"
# Low-latency multilingual model; good for short in-meeting utterances.
_DEFAULT_MODEL = "eleven_turbo_v2_5"
_API_ROOT = "https://api.elevenlabs.io/v1/text-to-speech"


class ElevenLabsSession:
    """Text → ElevenLabs PCM, appended to ``audio_sink_path`` (same contract
    as :class:`RealtimeSession`)."""

    def __init__(
        self,
        *,
        api_key: Optional[str],
        voice_id: Optional[str] = None,
        audio_sink_path: Optional[Path] = None,
        sample_rate: int = 24000,
        model_id: Optional[str] = None,
        instructions: Optional[str] = None,  # accepted for interface parity; unused
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.voice_id = (voice_id or _DEFAULT_VOICE_ID).strip()
        self.audio_sink_path = Path(audio_sink_path) if audio_sink_path else None
        self.sample_rate = int(sample_rate)
        self.model_id = (model_id or _DEFAULT_MODEL).strip()
        self.audio_bytes_out: int = 0
        self.last_audio_out_at: Optional[float] = None

    # ── lifecycle (no persistent socket; kept for interface parity) ────────

    def connect(self) -> None:
        if not self.api_key:
            raise RuntimeError(
                "ElevenLabs voice requires ELEVENLABS_API_KEY (or ELEVEN_API_KEY)"
            )
        # ElevenLabs only supports a fixed set of PCM rates.
        if self.sample_rate not in (16000, 22050, 24000, 44100):
            self.sample_rate = 24000

    def close(self) -> None:  # no socket to close
        return None

    # ── speak ──────────────────────────────────────────────────────────────

    def speak(self, text: str, timeout: float = 30.0) -> dict:
        """Synthesise ``text`` and append the PCM bytes to ``audio_sink_path``."""
        text = (text or "").strip()
        if not text:
            return {"ok": True, "audio_bytes": 0, "skipped": "empty"}

        url = (
            f"{_API_ROOT}/{self.voice_id}/stream"
            f"?output_format=pcm_{self.sample_rate}"
        )
        body = json.dumps(
            {
                "text": text,
                "model_id": self.model_id,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "xi-api-key": self.api_key,
                "content-type": "application/json",
                "accept": "audio/pcm",
            },
        )

        start = time.monotonic()
        sink_fp = None
        if self.audio_sink_path is not None:
            self.audio_sink_path.parent.mkdir(parents=True, exist_ok=True)
            sink_fp = open(self.audio_sink_path, "ab")
        bytes_written = 0
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    if sink_fp is not None:
                        sink_fp.write(chunk)
                        sink_fp.flush()
                    bytes_written += len(chunk)
                    self.audio_bytes_out += len(chunk)
                    self.last_audio_out_at = time.time()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300] if exc.fp else ""
            raise RuntimeError(f"ElevenLabs TTS {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"ElevenLabs TTS unreachable: {exc.reason}") from exc
        finally:
            if sink_fp is not None:
                sink_fp.close()

        return {
            "ok": True,
            "audio_bytes": bytes_written,
            "duration_ms": (time.monotonic() - start) * 1000.0,
            "provider": "elevenlabs",
        }
