"""Sous-salles pour le travail en groupe (phase 1.8).

Une sous-salle est une salle LiveKit à part, `vigil-{room_id}--{gid}`, rattachée à la salle
principale : pas de ligne `rooms` en plus. La configuration vit dans `rooms.breakouts`
(migration 027) : [{id, name, members: [identité], open}].

Qui entre dans quelle sous-salle :
  * qui anime la salle (propriétaire ; en formation, voir learn_link) → toutes ;
  * un participant → la sienne seulement.

Répartition automatique : les apprenants inscrits (formation) ou les membres fournis, en
tourniquet, dans l'ordre alphabétique des noms — reproductible, donc explicable.

La présence dans une sous-salle compte pour la salle principale : le webhook rattache
`vigil-{room_id}--{gid}` à `room_id`.
"""

from __future__ import annotations

from typing import Any

SEP = "--"


def livekit_room(room_id: str, gid: str) -> str:
    return f"vigil-{room_id}{SEP}{gid}"


def parent_room_id(livekit_name: str) -> str:
    """`vigil-<uuid>` ou `vigil-<uuid>--g1` → `<uuid>`."""
    return livekit_name.removeprefix("vigil-").split(SEP, 1)[0]


def distribute(people: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Répartit `people` ({id, name}) en `count` groupes, en tourniquet sur l'ordre des noms."""
    count = max(1, min(int(count), 20))
    groups = [{"id": f"g{i + 1}", "name": f"Groupe {i + 1}", "members": [], "open": True} for i in range(count)]
    ordered = sorted(people, key=lambda p: (str(p.get("name") or "").lower(), str(p["id"])))
    for i, person in enumerate(ordered):
        groups[i % count]["members"].append(str(person["id"]))
    return groups


def group_of(breakouts: list[dict[str, Any]], identity: str) -> dict[str, Any] | None:
    for g in breakouts or []:
        if g.get("open", True) and identity in (g.get("members") or []):
            return g
    return None
