"""Post-meeting structurer — turns the summarizer's close into a canvas-ready
artifact: an auto-laid-out decision-flow diagram (nodes + edges) and an
action-items table. This is what the editable artifact canvas (tldraw) renders
after a meeting.

Runs on the same HF council as the summarizer (``ask()``); the action table is
derived deterministically from the commitments, and the flow degrades to a
single node if the LLM is unavailable — so an artifact is always produced.
"""
from __future__ import annotations

from typing import Any

from winny.council.providers import ask
from winny.council.registry import worker_registry
from winny.council.summarizer import _parse_json

_FLOW_SYSTEM = (
    "You turn a meeting's decisions into a concise decision-flow diagram. "
    "Identify the core flow: the problem/context, the decision(s) taken, and the "
    "intended outcome. Respond ONLY with a JSON object matching exactly:\n"
    '{"nodes":[{"id":"n1","label":"short phrase","kind":"problem|decision|outcome"}],'
    ' "edges":[{"from":"n1","to":"n2"}]}\n'
    "Keep it to 3-6 nodes, labels under 6 words, grounded only in the input — no invention."
)


def _layout(nodes: list[dict]) -> list[dict]:
    """Deterministic left-to-right layout grouped by kind (problem→decision→outcome),
    so we never depend on the model for coordinates."""
    col_of = {"problem": 0, "decision": 1, "outcome": 2}
    cols: dict[int, list] = {}
    for n in nodes:
        c = col_of.get(str(n.get("kind", "decision")).lower(), 1)
        cols.setdefault(c, []).append(n)
    out: list[dict] = []
    for c, items in cols.items():
        for i, n in enumerate(items):
            out.append({
                "id": str(n.get("id")),
                "label": str(n.get("label") or "")[:60],
                "kind": str(n.get("kind") or "decision").lower(),
                "x": 60 + c * 230,
                "y": 60 + i * 120,
            })
    return out


def _table_from_commitments(commitments: list[dict]) -> dict[str, Any]:
    rows = [
        [str(c.get("text") or "")[:160], str(c.get("owner") or ""), str(c.get("due") or "")]
        for c in commitments
        if isinstance(c, dict) and (c.get("text") or "").strip()
    ]
    return {"columns": ["Action item", "Owner", "Due"], "rows": rows}


async def structure_meeting(
    *,
    summary_markdown: str = "",
    decisions: list[str] | None = None,
    commitments: list[dict] | None = None,
    topic: str = "",
) -> dict[str, Any]:
    """Returns {nodes, edges, table} ready for the artifact canvas."""
    decisions = decisions or []
    table = _table_from_commitments(commitments or [])
    nodes: list[dict] = []
    edges: list[dict] = []

    basis = (summary_markdown or "").strip()
    if decisions:
        basis += "\nDecisions:\n" + "\n".join(f"- {d}" for d in decisions)
    if basis.strip():
        try:
            worker = worker_registry()["primary"]
            result = await ask(
                worker,
                f"Topic: {topic or 'unspecified'}\n\n{basis[:6000]}\n\nProduce the decision-flow JSON.",
                system=_FLOW_SYSTEM,
                temperature=0.3,
                max_tokens=700,
            )
            parsed = _parse_json(result.get("output", "")) or {}
            raw_nodes = [n for n in (parsed.get("nodes") or []) if isinstance(n, dict) and n.get("id")]
            edges = [
                {"from": str(e.get("from")), "to": str(e.get("to"))}
                for e in (parsed.get("edges") or [])
                if isinstance(e, dict) and e.get("from") and e.get("to")
            ]
            nodes = _layout(raw_nodes)
        except Exception:  # noqa: BLE001 — always produce *something*
            nodes, edges = [], []

    if not nodes and (decisions or topic):
        nodes = _layout([
            {"id": "d1", "label": (decisions[0] if decisions else topic), "kind": "decision"}
        ])
        edges = []
    return {"nodes": nodes, "edges": edges, "table": table}


async def diagram_from_prompt(*, prompt: str, context: str = "", topic: str = "") -> dict[str, Any]:
    """On-demand diagram for the canvas: turn a prompt (+ board context) into an
    auto-laid-out node/edge graph the user can then edit. Returns {nodes, edges}."""
    basis = prompt.strip()
    if context.strip():
        basis += "\n\nExisting board:\n" + context.strip()[:3000]
    if not basis:
        return {"nodes": [], "edges": []}
    try:
        worker = worker_registry()["primary"]
        result = await ask(
            worker,
            f"Topic: {topic or 'unspecified'}\n\n{basis[:5000]}\n\nProduce the diagram JSON.",
            system=_FLOW_SYSTEM,
            temperature=0.4,
            max_tokens=900,
        )
        parsed = _parse_json(result.get("output", "")) or {}
        raw_nodes = [n for n in (parsed.get("nodes") or []) if isinstance(n, dict) and n.get("id")]
        edges = [
            {"from": str(e.get("from")), "to": str(e.get("to"))}
            for e in (parsed.get("edges") or [])
            if isinstance(e, dict) and e.get("from") and e.get("to")
        ]
        return {"nodes": _layout(raw_nodes), "edges": edges}
    except Exception:  # noqa: BLE001
        return {"nodes": [], "edges": []}
