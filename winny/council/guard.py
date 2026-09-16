"""Coupe-circuit IA — l'app reste utilisable quand les modèles ne répondent pas.

Tous les appels de modèle passent par ``providers.ask``. Ce module lui dit, avant chaque
appel, s'il a le droit d'essayer, et enregistre ce qui s'est passé :

  * **Interrupteur général** — ``AI_ENABLED=false`` coupe tous les appels.
  * **Interrupteurs par fonction** — ``AI_DISABLED_FEATURES=meeting,mail`` coupe ces
    fonctions seulement. La fonction en cours est posée par la passerelle
    (``use_feature``) pour la durée d'une requête.
  * **Délai maximal** — ``AI_TIMEOUT_S`` (30 s par défaut) plafonne chaque appel ; un
    appelant peut demander moins, jamais plus.
  * **Coupe-circuit par fournisseur** — après ``AI_BREAKER_FAILURES`` échecs consécutifs
    (3), le fournisseur est ouvert pendant ``AI_BREAKER_COOLDOWN_S`` (60 s) : les appels
    échouent immédiatement au lieu d'attendre le délai. À l'expiration, un seul appel
    d'essai ; s'il réussit, le circuit se referme.

Quand un appel est refusé, ``ask`` renvoie la réponse neutre existante (``stub``) marquée
``ai_unavailable`` : les pages retombent sur leur comportement déterministe et l'app
affiche « assistant indisponible » d'après ``health()``.
"""

from __future__ import annotations

import contextvars
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

_feature: contextvars.ContextVar[str | None] = contextvars.ContextVar("ai_feature", default=None)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except ValueError:
        return default


def ai_enabled() -> bool:
    return os.getenv("AI_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def disabled_features() -> set[str]:
    return {f.strip().lower() for f in os.getenv("AI_DISABLED_FEATURES", "").split(",") if f.strip()}


def current_feature() -> str | None:
    return _feature.get()


def set_feature(name: str | None) -> contextvars.Token:
    return _feature.set(name)


@contextmanager
def use_feature(name: str) -> Iterator[None]:
    token = _feature.set(name)
    try:
        yield
    finally:
        _feature.reset(token)


def max_timeout(requested: float) -> float:
    return min(requested, _env_float("AI_TIMEOUT_S", 30.0))


@dataclass
class _Circuit:
    failures: int = 0
    open_until: float = 0.0
    probing: bool = False
    last_error: str | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None
    configured: bool = True
    calls: int = field(default=0)


_circuits: dict[str, _Circuit] = {}


def _circuit(family: str) -> _Circuit:
    return _circuits.setdefault(family or "unknown", _Circuit())


def refusal(family: str) -> str | None:
    """Pourquoi cet appel ne doit pas partir, ou None s'il peut partir."""
    if not ai_enabled():
        return "ai_disabled"
    feat = current_feature()
    if feat and feat in disabled_features():
        return f"feature_disabled:{feat}"
    c = _circuit(family)
    now = time.monotonic()
    if c.open_until > now:
        return "circuit_open"
    if c.open_until and not c.probing:
        # Délai écoulé : un seul appel d'essai à la fois.
        c.probing = True
        return None
    if c.open_until and c.probing:
        return "circuit_open"
    return None


def record_success(family: str) -> None:
    c = _circuit(family)
    c.failures = 0
    c.open_until = 0.0
    c.probing = False
    c.configured = True
    c.calls += 1
    c.last_success_at = time.time()


def record_failure(family: str, reason: str) -> None:
    c = _circuit(family)
    c.calls += 1
    c.failures += 1
    c.probing = False
    c.last_error = reason[:300]
    c.last_failure_at = time.time()
    if c.failures >= int(_env_float("AI_BREAKER_FAILURES", 3)):
        c.open_until = time.monotonic() + _env_float("AI_BREAKER_COOLDOWN_S", 60.0)


def record_not_configured(family: str, reason: str) -> None:
    c = _circuit(family)
    c.configured = False
    c.probing = False
    c.last_error = reason[:300]


def release_probe(family: str) -> None:
    """Un appel d'essai terminé sans verdict (clé absente, famille inconnue) libère la place."""
    _circuit(family).probing = False


def health() -> dict[str, Any]:
    """État lisible par l'app : disponible ou non, et pourquoi."""
    now = time.monotonic()
    providers: dict[str, Any] = {}
    for fam, c in sorted(_circuits.items()):
        if not c.configured:
            state = "not_configured"
        elif c.open_until > now:
            state = "open"
        elif c.open_until:
            state = "half_open"
        else:
            state = "closed"
        providers[fam] = {
            "state": state,
            "consecutive_failures": c.failures,
            "retry_in_s": max(0, round(c.open_until - now)) if c.open_until > now else 0,
            "last_error": c.last_error,
            "last_success_at": c.last_success_at,
            "last_failure_at": c.last_failure_at,
        }
    return {
        "enabled": ai_enabled(),
        "disabled_features": sorted(disabled_features()),
        "timeout_s": _env_float("AI_TIMEOUT_S", 30.0),
        "providers": providers,
    }


def reset() -> None:
    """Pour les tests."""
    _circuits.clear()
