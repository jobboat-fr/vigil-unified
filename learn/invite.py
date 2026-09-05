"""Créer le compte d'accès d'un apprenant converti — Supabase Admin API.

Pourquoi ce module existe : `learn_profiles.id` **est** l'identifiant Supabase Auth. Ce
n'est pas un détail de plomberie, c'est ce que compare chaque politique de portée « self ».
Un profil ne peut donc pas être créé avec une clé inventée puis rattaché plus tard : la
clé primaire est déjà référencée par `learn_enrollments`, et par tout l'émargement qui en
dépend.

L'invitation précède donc la conversion, et elle vit ici plutôt que dans une fonction SQL
parce qu'elle est un appel réseau à un service d'authentification — pas une opération de
base de données.

Dégradation : sans `LEARN_SUPABASE_URL` / `LEARN_SUPABASE_SERVICE_KEY`, la conversion reste
possible en fournissant `auth_user_id` explicitement. La route le dit clairement plutôt que
d'échouer avec une erreur de contrainte.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

SUPABASE_URL = os.getenv("LEARN_SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.getenv("LEARN_SUPABASE_SERVICE_KEY", "")
TIMEOUT = float(os.getenv("LEARN_INVITE_TIMEOUT", "20"))


class InviteUnavailable(RuntimeError):
    """Le service d'authentification n'est pas configuré ou ne répond pas."""


class InviteRefused(RuntimeError):
    """Supabase a refusé — adresse invalide, quota atteint. Ne pas réessayer tel quel."""


def configured() -> bool:
    return bool(SUPABASE_URL and SERVICE_KEY)


def _headers() -> dict[str, str]:
    return {"apikey": SERVICE_KEY,
            "Authorization": f"Bearer {SERVICE_KEY}",
            "Content-Type": "application/json"}


async def find_or_invite(email: str, full_name: str,
                         redirect_to: str | None = None) -> str:
    """Renvoie l'identifiant Auth de cette adresse, en l'invitant si elle n'existe pas.

    Idempotent volontairement : réinviter quelqu'un qui a déjà un compte lui enverrait un
    second lien et casserait la conversion avec un doublon. On cherche d'abord.
    """
    if not configured():
        raise InviteUnavailable(
            "LEARN_SUPABASE_URL / LEARN_SUPABASE_SERVICE_KEY absents : "
            "fournir auth_user_id explicitement")

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            found = await client.get(
                f"{SUPABASE_URL}/auth/v1/admin/users",
                params={"page": 1, "per_page": 1, "email": email},
                headers=_headers())
        except httpx.HTTPError as e:
            raise InviteUnavailable(f"auth injoignable ({type(e).__name__})") from e

        if found.status_code < 400:
            users = (found.json() or {}).get("users") or []
            for u in users:
                if str(u.get("email", "")).lower() == email.lower() and u.get("id"):
                    return str(u["id"])

        payload: dict[str, Any] = {"email": email, "data": {"full_name": full_name}}
        if redirect_to:
            payload["redirect_to"] = redirect_to
        try:
            res = await client.post(f"{SUPABASE_URL}/auth/v1/invite",
                                    json=payload, headers=_headers())
        except httpx.HTTPError as e:
            raise InviteUnavailable(f"auth injoignable ({type(e).__name__})") from e

    if res.status_code >= 500:
        raise InviteUnavailable(f"auth en erreur ({res.status_code})")
    if res.status_code >= 400:
        raise InviteRefused(f"invitation refusée ({res.status_code}) : {res.text[:200]}")

    uid = (res.json() or {}).get("id")
    if not uid:
        raise InviteRefused("réponse d'invitation sans identifiant")
    return str(uid)
