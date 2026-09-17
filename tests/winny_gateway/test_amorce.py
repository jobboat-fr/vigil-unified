"""L'amorce agentique précède chaque appel à un modèle."""
from __future__ import annotations

import asyncio

from winny.council import guard, providers
from winny.council.amorce import AMORCE, systeme_amorce


def test_amorce_en_tete_avec_les_outils_de_la_fonction(monkeypatch):
    vu = {}

    async def faux_dispatch(family, model, system, user_prompt, *a):
        vu["system"] = system
        return {"output": "ok", "stub": False}

    monkeypatch.setattr(providers, "_dispatch", faux_dispatch)
    monkeypatch.setattr(guard, "refusal", lambda fam: None)
    with guard.use_feature("studio"):
        asyncio.run(providers.ask({"family": "together", "model": "m"}, "demande", system="Consigne propre."))
    s = vu["system"]
    assert s.startswith(AMORCE)
    assert "fonction « studio »" in s and "brainstorming" in s
    assert s.rstrip().endswith("Consigne propre.")
    assert s.index("vérifie d'abord les outils") < s.index("Consigne propre.")


def test_amorce_sans_fonction_ni_consigne():
    s = systeme_amorce(None, None)
    assert s.startswith(AMORCE) and "données fournies" in s
