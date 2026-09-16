"""Lecture des créneaux LEARN pour la salle de réunion.

La passerelle lit directement les tables LEARN (même projet Supabase, clé de service) pour
décider qui entre dans la salle d'un créneau, et à quel titre. Aucune écriture ici : LEARN
reste la source de vérité des sessions, des créneaux et des inscriptions.

Qui entre :
  * le formateur du créneau → anime (host) ;
  * super_admin, ou admin du même organisme → anime ;
  * apprenant inscrit à la session (inscrit, confirmé) → participe ;
  * entreprise dont un salarié est inscrit → participe ;
  * tout autre → refusé.

Quand : un créneau annulé, une session annulée ou présentielle n'a pas de salle. On entre à
partir de ROOM_JOIN_EARLY_MIN minutes avant le début (30 ; 60 pour qui anime) et jusqu'à
ROOM_JOIN_LATE_MIN minutes après la fin (30).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from winny_gateway.db import db_select

VALID_ENROLLMENT = {"inscrit", "confirme"}
ADMIN_ROLES = {"super_admin", "admin"}


def _minutes(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


@dataclass
class SlotAccess:
    slot: dict[str, Any]
    session: dict[str, Any]
    role: str  # "host" | "participant"
    display_name: str


def _refuse(code: int, error: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=code, detail={"error": error, **extra})


async def slot_access(slot_id: str, user: dict[str, Any], learn_role: str | None,
                      now: datetime | None = None) -> SlotAccess:
    now = now or datetime.now(UTC)
    uid = str(user.get("sub") or "")
    meta = user.get("app_metadata") or {}

    slots = await db_select("learn_session_slots", filters={"id": slot_id}, limit=1, allow_unscoped=True)
    if not slots:
        raise _refuse(status.HTTP_404_NOT_FOUND, "slot_not_found")
    slot = slots[0]
    sessions = await db_select("learn_sessions", filters={"id": slot["session_id"]}, limit=1, allow_unscoped=True)
    if not sessions:
        raise _refuse(status.HTTP_404_NOT_FOUND, "session_not_found")
    session = sessions[0]

    if learn_role != "super_admin" and str(meta.get("tenant_id") or "") != str(slot.get("tenant_id") or ""):
        # Un autre organisme : on ne confirme même pas que le créneau existe.
        raise _refuse(status.HTTP_404_NOT_FOUND, "slot_not_found")
    if session.get("modality") not in ("distanciel", "mixte"):
        raise _refuse(status.HTTP_409_CONFLICT, "not_remote", modality=session.get("modality"))
    if session.get("status") == "cancelled" or slot.get("status") == "cancelled":
        raise _refuse(status.HTTP_409_CONFLICT, "slot_cancelled")

    profiles = await db_select("learn_profiles", filters={"id": uid}, limit=1, allow_unscoped=True)
    profile = profiles[0] if profiles else {}
    name = profile.get("full_name") or str(user.get("email") or "Participant").split("@")[0]

    if slot.get("formateur_id") and str(slot["formateur_id"]) == uid:
        role = "host"
    elif learn_role in ADMIN_ROLES:
        role = "host"
    elif learn_role == "apprenant":
        enr = await db_select("learn_enrollments",
                              filters={"session_id": session["id"], "apprenant_id": uid},
                              limit=5, allow_unscoped=True)
        if not any(e.get("status") in VALID_ENROLLMENT for e in enr):
            raise _refuse(status.HTTP_403_FORBIDDEN, "not_enrolled")
        role = "participant"
    elif learn_role == "entreprise" and profile.get("company_id"):
        enr = await db_select("learn_enrollments",
                              filters={"session_id": session["id"], "company_id": profile["company_id"]},
                              limit=50, allow_unscoped=True)
        if not any(e.get("status") in VALID_ENROLLMENT for e in enr):
            raise _refuse(status.HTTP_403_FORBIDDEN, "not_enrolled")
        role = "participant"
    else:
        raise _refuse(status.HTTP_403_FORBIDDEN, "not_in_session")

    early = _minutes("ROOM_JOIN_EARLY_MIN", 30) * (2 if role == "host" else 1)
    late = _minutes("ROOM_JOIN_LATE_MIN", 30)
    opens = _dt(slot["starts_at"]) - timedelta(minutes=early)
    closes = _dt(slot["ends_at"]) + timedelta(minutes=late)
    if now < opens:
        raise _refuse(status.HTTP_425_TOO_EARLY, "too_early", opens_at=opens.isoformat())
    if now > closes:
        raise _refuse(status.HTTP_410_GONE, "slot_over")

    return SlotAccess(slot=slot, session=session, role=role, display_name=name)
