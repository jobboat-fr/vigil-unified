"""AZZMIN en salle (phase 1.4) : il ne parle que si l'algorithme d'intervention le décide.

LiveKit n'est pas installé dans l'environnement de test : ses modules sont remplacés par des
doublures minimales, juste assez pour importer le worker et appeler le crochet de tour de
parole. Ce qui est testé est la règle, pas LiveKit.
"""
from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types

import pytest


class StopResponse(Exception):
    pass


def _stub_livekit(monkeypatch):
    agents = types.ModuleType("livekit.agents")

    class Agent:
        def __init__(self, instructions=""):
            self.instructions = instructions
            self.session = None

    for name in ("AgentSession", "JobContext", "RoomInputOptions", "RoomOutputOptions", "WorkerOptions"):
        setattr(agents, name, type(name, (), {"__init__": lambda self, *a, **k: None}))
    agents.Agent = Agent
    agents.cli = types.SimpleNamespace(run_app=lambda *a, **k: None)
    agents.llm = types.ModuleType("livekit.agents.llm")
    agents.llm.StopResponse = StopResponse
    agents.llm.ChatContext = object
    agents.llm.ChatMessage = object
    plugins = types.ModuleType("livekit.plugins")
    plugins.groq = types.ModuleType("groq")
    plugins.silero = types.ModuleType("silero")
    lk = types.ModuleType("livekit")
    lk.rtc = types.ModuleType("livekit.rtc")
    lk.agents, lk.plugins = agents, plugins
    for mod_name, mod in {
        "livekit": lk, "livekit.rtc": lk.rtc, "livekit.agents": agents, "livekit.agents.llm": agents.llm,
        "livekit.plugins": plugins,
    }.items():
        monkeypatch.setitem(sys.modules, mod_name, mod)


@pytest.fixture
def worker(monkeypatch):
    _stub_livekit(monkeypatch)
    path = pathlib.Path(__file__).resolve().parents[2] / "services" / "meeting_agent" / "worker.py"
    spec = importlib.util.spec_from_file_location("azzmin_worker", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakePasserelle:
    def __init__(self, decision=None, fail=False):
        self.decision = decision or {}
        self.fail = fail
        self.fil: list[tuple[str, str]] = []

    async def ajouter(self, speaker, text):
        if self.fail:
            raise RuntimeError("passerelle en panne")
        self.fil.append((speaker, text))

    async def decider(self, topic):
        return self.decision


class FakeSession:
    def __init__(self):
        self.dit: list[str] = []

    def say(self, text, **_kw):
        self.dit.append(text)


def _tour(worker, passerelle, texte="Comment calcule-t-on le taux d'atteinte ?"):
    agent = worker.AgentDeSalle(instructions="", passerelle=passerelle, topic="IA 360",
                                noms={"u-form": "Claire (formatrice)"})
    agent.session = FakeSession()
    agent.orateur = "u-form"
    msg = types.SimpleNamespace(text_content=texte)
    with pytest.raises(StopResponse):
        asyncio.run(agent.on_user_turn_completed(None, msg))
    return agent


def test_se_tait_quand_l_algorithme_dit_non(worker):
    p = FakePasserelle({"speak": False, "reason": "no_specialist_signal"})
    agent = _tour(worker, p)
    assert agent.session.dit == []
    assert p.fil == [("Claire (formatrice)", "Comment calcule-t-on le taux d'atteinte ?")]


def test_parle_quand_l_algorithme_dit_oui_et_l_ecrit_au_fil(worker):
    p = FakePasserelle({"speak": True, "message": "Le taux se calcule sur les apprenants présents.", "urgency": "normal"})
    agent = _tour(worker, p)
    assert agent.session.dit == ["Le taux se calcule sur les apprenants présents."]
    assert p.fil[-1] == ("AZZMIN", "Le taux se calcule sur les apprenants présents.")


def test_silence_si_passerelle_en_panne(worker):
    agent = _tour(worker, FakePasserelle(fail=True))
    assert agent.session.dit == []


def test_silence_si_oui_sans_message(worker):
    agent = _tour(worker, FakePasserelle({"speak": True, "message": "  "}))
    assert agent.session.dit == []


def test_l_ia_se_reconnait_dans_le_fil():
    from winny.council.intervention import _kind
    assert _kind("AZZMIN") == "ai"


def test_entetes_agent_et_delegation(worker, monkeypatch):
    w = worker
    monkeypatch.setenv("VTLVS_AGENT_TOKEN", "vtlvs_ag_x")
    monkeypatch.setenv("WW_SERVICE_TOKEN", "svc")
    h = w.entetes_passerelle("owner", "deleg")
    assert h["Authorization"] == "Bearer vtlvs_ag_x" and h["X-Vtlvs-Delegation"] == "deleg"
    assert "X-WinnyWoo-User-Id" not in h
    repli = w.entetes_passerelle("owner", None)
    assert repli["Authorization"] == "Bearer svc" and repli["X-WinnyWoo-User-Id"] == "owner"
