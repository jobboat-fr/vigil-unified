"""Toutes les routes réellement servies par l'application, avec leurs dépendances effectives.

FastAPI 0.137 ne met plus à plat les routeurs inclus : `app.routes` contient des blocs
`_IncludedRouter`, et seul `effective_route_contexts()` donne le chemin complet et les
dépendances héritées du montage. Un balayage qui ne lit que `app.routes` ne voit presque rien
(le 29/09, il n'avait vu que /health et conclu à tort que tout était gardé).
"""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi.routing import APIRoute


def routes(app: Any) -> Iterator[tuple[str, set[str], Any, Any]]:
    """(chemin, méthodes, fonction servie, dependant) pour chaque route HTTP."""
    for r in app.routes:
        if isinstance(r, APIRoute):
            yield r.path, set(r.methods or ()), r.endpoint, r.dependant
        elif hasattr(r, "effective_route_contexts"):
            for c in r.effective_route_contexts():
                if c.dependant is not None:
                    yield c.path, set(c.methods or ()), c.endpoint, c.dependant


def dependances(dependant: Any) -> set[Any]:
    """Toutes les fonctions de dépendance, récursivement."""
    vues: set[Any] = set()
    pile = list(dependant.dependencies)
    while pile:
        d = pile.pop()
        if d.call is not None:
            vues.add(d.call)
        pile.extend(d.dependencies)
    return vues
