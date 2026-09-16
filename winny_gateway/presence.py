"""Présence en salle : webhook LiveKit, puis rapprochement avec l'émargement LEARN.

Le webhook enregistre chaque entrée et sortie (table room_presence). Le rapprochement
calcule, pour une salle de créneau LEARN, la présence de chaque apprenant inscrit et la
compare à la feuille d'émargement (vue learn_attendance_sheet). Il signale ; il ne signe,
ne corrige, ni ne justifie jamais rien — l'émargement reste l'acte du formateur et de
l'apprenant dans LEARN.

Écarts signalés :
  present_non_signe  — présent en visio au moins SEUIL du créneau, aucune signature ;
  signe_non_present  — signé, mais présent moins de 10 % du créneau ;
  presence_courte    — signé, présent, mais moins de SEUIL du créneau.
SEUIL = ROOM_PRESENCE_MIN_RATIO (0,5 par défaut).

Signature du webhook : LiveKit envoie un JWT (HS256, secret de l'API) dont la revendication
`sha256` est l'empreinte base64 du corps. Vérifiée ici, sans dépendance supplémentaire.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import UTC, datetime
from typing import Any

import jwt


class WebhookRefused(Exception):
    pass


def verify_webhook(body: bytes, authorization: str | None) -> None:
    key, secret = os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET")
    if not (key and secret):
        raise WebhookRefused("livekit_not_configured")
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        raise WebhookRefused("missing_signature")
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_aud": False})
    except jwt.PyJWTError as exc:
        raise WebhookRefused("bad_signature") from exc
    if claims.get("iss") != key:
        raise WebhookRefused("bad_issuer")
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    if claims.get("sha256") != digest:
        raise WebhookRefused("body_mismatch")


def _dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


def presence_seconds(events: list[dict[str, Any]], start: datetime, end: datetime,
                     now: datetime | None = None) -> float:
    """Secondes passées dans la salle pendant [start, end], d'après les entrées/sorties."""
    total = 0.0
    opened: datetime | None = None
    for e in sorted(events, key=lambda e: _dt(e["at"])):
        at = _dt(e["at"])
        if e["event"] == "joined":
            if opened is None:
                opened = at
        elif e["event"] == "left" and opened is not None:
            a, b = max(opened, start), min(at, end)
            total += max(0.0, (b - a).total_seconds())
            opened = None
    if opened is not None:
        a, b = max(opened, start), min(now or datetime.now(UTC), end)
        total += max(0.0, (b - a).total_seconds())
    return total


def reconcile(slot: dict[str, Any], learners: list[dict[str, Any]], sheet: list[dict[str, Any]],
              events: list[dict[str, Any]], now: datetime | None = None) -> list[dict[str, Any]]:
    start, end = _dt(slot["starts_at"]), _dt(slot["ends_at"])
    span = max(1.0, (end - start).total_seconds())
    seuil = float(os.getenv("ROOM_PRESENCE_MIN_RATIO", "0.5") or 0.5)
    signed = {str(r["apprenant_id"]): r for r in sheet if r.get("signed_in_at")}
    out = []
    for learner in learners:
        uid = str(learner["apprenant_id"])
        ratio = presence_seconds([e for e in events if e["identity"] == uid], start, end, now) / span
        row = signed.get(uid)
        ecart = None
        if row is None and ratio >= seuil:
            ecart = "present_non_signe"
        elif row is not None and ratio < 0.1:
            ecart = "signe_non_present"
        elif row is not None and ratio < seuil:
            ecart = "presence_courte"
        out.append({
            "apprenant_id": uid,
            "nom": learner.get("full_name") or uid,
            "presence_ratio": round(ratio, 2),
            "signe": row is not None,
            "ecart": ecart,
        })
    return out
