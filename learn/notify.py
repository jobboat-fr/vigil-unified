"""LEARN → hbs-backend : le trajet d'envoi.

LEARN rédige et enregistre ; il n'envoie pas. Le service `hbs-backend` détient déjà le pont
Caddy vers l'agent Hermes et WhatsApp, ainsi que la règle de confirmation qui existe depuis
sa v1. Reproduire ce chemin ici donnerait deux endroits capables de parler au nom de
l'organisme, donc deux endroits à sécuriser et à auditer.

Le contrôle humain est vérifié deux fois sur le même trajet, ce qui est délibéré :

    ici          — refus si `approved_at` est nul, avant tout appel réseau
    en base      — `learn_notif_sent_needs_approval` interdit le statut « envoyé »
    hbs-backend  — 412 si `approved_by` manque dans la charge utile

Un assistant peut remplir la file aux deux extrémités. Il ne peut la vider à aucune.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

BRIDGE_URL = os.getenv("LEARN_NOTIFY_URL", "").rstrip("/")
BRIDGE_TOKEN = os.getenv("LEARN_NOTIFY_TOKEN", "")
TIMEOUT = float(os.getenv("LEARN_NOTIFY_TIMEOUT", "20"))


class NotifyUnavailable(RuntimeError):
    """Le pont n'est pas configuré ou ne répond pas. La ligne reste en file."""


class NotifyRefused(RuntimeError):
    """Le pont a refusé — approbation manquante, destinataire absent. Ne pas réessayer."""


def configured() -> bool:
    return bool(BRIDGE_URL and BRIDGE_TOKEN)


async def dispatch(row: dict[str, Any]) -> dict[str, Any]:
    """Envoie une notification approuvée via hbs-backend.

    `row` est la ligne `learn_notifications` telle qu'elle sort de la base — donc portant
    déjà `approved_by` et `approved_at`, puisque c'est la contrainte de table qui l'exige.
    On revérifie ici pour ne pas dépendre de l'appelant : un envoi non validé ne doit même
    pas quitter le processus.
    """
    if not row.get("approved_at") or not row.get("approved_by"):
        raise NotifyRefused(
            "notification non approuvée — un humain nommé doit valider avant l'envoi")
    if not configured():
        raise NotifyUnavailable(
            "LEARN_NOTIFY_URL / LEARN_NOTIFY_TOKEN absents : envoi impossible")

    payload = {
        "notification_id": str(row["id"]),
        "kind": row.get("kind") or "notification",
        "subject": row.get("subject") or "",
        "body": row.get("body") or "",
        "to": row.get("email"),
        "approved_by": str(row["approved_by"]),
        "tenant": str(row.get("tenant_id") or ""),
    }

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            res = await client.post(
                f"{BRIDGE_URL}/learn/notify",
                json=payload,
                headers={"Authorization": f"Bearer {BRIDGE_TOKEN}"},
            )
    except httpx.HTTPError as e:
        # Transport : la demande était bonne, le pont est absent. La ligne repasse en
        # « échec » et reste visible plutôt que d'être perdue.
        raise NotifyUnavailable(f"pont injoignable ({type(e).__name__})") from e

    if res.status_code == 412:
        raise NotifyRefused("le pont exige une approbation nommée")
    if res.status_code >= 500:
        raise NotifyUnavailable(f"pont en erreur ({res.status_code})")
    if res.status_code >= 400:
        raise NotifyRefused(f"envoi refusé ({res.status_code}) : {res.text[:200]}")

    return res.json()
