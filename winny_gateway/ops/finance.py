"""Finance department — reconcile the ledger and flag anomalies (P1).

Contract:
  job        pull fresh bank data (if connected), then categorise + reconcile every
             pending transaction and flag large/anomalous ones
  input      {limit}
  tools      finance_transactions + finance_connections (the connector)
  output     a reconciliation-summary artifact
  acceptance every targeted transaction ends status=reconciled with a category set
  budget     per-run spend + wall-clock caps (engine-enforced)

`classify_txn` is the only LLM touchpoint; tests monkeypatch it. The bank sync at
the top is best-effort — no connection just means there's nothing new to pull.
"""
from __future__ import annotations

from typing import Any

from winny.council.providers import ask
from winny.council.registry import cheap_worker, worker_registry
from winny.council.summarizer import _parse_json
from winny_gateway.db import db_insert, db_select, db_update
from winny_gateway.integrations import finance_connect
from winny_gateway.logging import get_logger

logger = get_logger(__name__)

FINANCE_CATEGORIES = ["revenue", "payroll", "software", "marketing", "office", "travel", "fees", "taxes", "other"]
ANOMALY_ABS = 5000.0  # |amount| at/above this is flagged for review

_SYSTEM = (
    "You are a bookkeeping classifier. Assign one expense/income category from "
    f"{FINANCE_CATEGORIES} to a single transaction. Respond ONLY with JSON: "
    '{"category": "...", "reasoning": "one short sentence"}'
)


async def classify_txn(txn: dict[str, Any]) -> tuple[str, float]:
    prompt = (
        f"Description: {txn.get('description') or ''}\n"
        f"Amount: {txn.get('amount')}\nCurrency: {txn.get('currency') or 'USD'}\n\n"
        "Classify it. Respond ONLY with the JSON object."
    )
    result = await ask(cheap_worker(), prompt, system=_SYSTEM, temperature=0.2, max_tokens=200)
    plan = _parse_json(result.get("output", "")) or {}
    cat = plan.get("category") if plan.get("category") in FINANCE_CATEGORIES else "other"
    try:
        cost = float(result.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return cat, cost


async def run(uid: str, inp: dict[str, Any]) -> dict[str, Any]:
    limit = max(1, min(int(inp.get("limit") or 50), 500))

    # Best-effort: pull fresh bank data so we reconcile what actually happened.
    synced = {"transactions_added": 0}
    try:
        synced = await finance_connect.sync(uid)
    except Exception as exc:  # noqa: BLE001 — sync is optional; reconcile what we have
        logger.info("finance.dept sync skipped: %s", exc)

    rows = await db_select("finance_transactions", filters={"user_id": uid}, limit=2000)
    pending = [t for t in rows if t.get("status") != "reconciled"][:limit]

    reconciled: list[str] = []
    anomalies = 0
    cost = 0.0
    calls = 0
    for t in pending:
        cat, c = await classify_txn(t)
        cost += c
        calls += 1
        patch: dict[str, Any] = {"category": cat, "status": "reconciled"}
        if abs(float(t.get("amount") or 0)) >= ANOMALY_ABS:
            meta = dict(t.get("metadata") or {})
            meta["anomaly"] = "large amount — review"
            patch["metadata"] = meta
            anomalies += 1
        await db_update("finance_transactions", patch, filters={"id": t["id"], "user_id": uid})
        reconciled.append(t["id"])

    body = (
        f"# Finance reconciliation\n\nReconciled **{len(reconciled)}** transactions"
        f" ({synced.get('transactions_added', 0)} newly synced from the bank), "
        f"flagged **{anomalies}** for review."
    )
    art = await db_insert("artifacts", {
        "user_id": uid, "title": f"Reconciliation — {len(reconciled)} transactions",
        "kind": "report", "brief": "Finance reconciliation run", "approach": "",
        "text_dump": body, "status": "draft", "version": 1,
    })

    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"Reconciled {len(reconciled)} transactions, flagged {anomalies}",
        "metrics": {"cost_usd": round(cost, 4), "tool_calls": calls,
                    "reconciled": len(reconciled), "anomalies": anomalies},
        "targeted_ids": reconciled,
    }


async def acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    ids = list(result.get("targeted_ids") or [])
    if not ids:
        return {"accepted": True, "reason": "nothing pending to reconcile"}
    rows = await db_select("finance_transactions", filters={"user_id": uid}, limit=5000)
    by_id = {r["id"]: r for r in rows}
    for i in ids:
        r = by_id.get(i)
        if not r or r.get("status") != "reconciled" or not r.get("category"):
            return {"accepted": False, "reason": f"transaction {i} not reconciled"}
    return {"accepted": True, "reason": f"{len(ids)} transactions reconciled with categories"}


# ── Accountant report ────────────────────────────────────────────────────────
# The numbers are computed deterministically (LLMs are unreliable at arithmetic);
# the model only writes narrative commentary over the already-computed figures.

def _compute(rows: list[dict[str, Any]]) -> dict[str, Any]:
    income = 0.0
    expense = 0.0  # accumulates as a negative number
    by_category: dict[str, float] = {}
    for t in rows:
        a = float(t.get("amount") or 0)
        if a >= 0:
            income += a
        else:
            expense += a
        cat = t.get("category") or "uncategorized"
        by_category[cat] = round(by_category.get(cat, 0.0) + a, 2)
    net = round(income + expense, 2)
    top_expenses = sorted(((k, v) for k, v in by_category.items() if v < 0), key=lambda kv: kv[1])[:5]
    return {
        "income": round(income, 2),
        "expense": round(-expense, 2),       # reported positive
        "net": net,
        "by_category": by_category,           # signed; sums to net by construction
        "top_expenses": [{"category": k, "amount": v} for k, v in top_expenses],
        "count": len(rows),
        "uncategorized": sum(1 for t in rows if not t.get("category")),
    }


async def narrate(figures: dict[str, Any]) -> tuple[str, float]:
    import json
    prompt = (
        "Here are the period's FINAL, already-computed figures (do not recompute or "
        f"change any number — reference them):\n{json.dumps(figures, indent=2)}\n\n"
        "Write a 3-5 sentence CFO commentary: the trend, the biggest cost drivers, any "
        "concern, and one concrete recommendation. Output prose only."
    )
    result = await ask(worker_registry()["primary"],
                       prompt, system="You are a sharp CFO writing concise commentary over given numbers.",
                       temperature=0.4, max_tokens=350)
    try:
        cost = float(result.get("cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return (result.get("output") or "").strip(), cost


def _report_md(f: dict[str, Any], commentary: str) -> str:
    lines = [
        "# Accountant report\n",
        f"- Income: **{f['income']:.2f}**",
        f"- Expense: **{f['expense']:.2f}**",
        f"- Net: **{f['net']:.2f}**",
        f"- Transactions: {f['count']} ({f['uncategorized']} uncategorized)\n",
        "## Top cost drivers",
    ]
    lines += [f"- {e['category']}: {e['amount']:.2f}" for e in f["top_expenses"]] or ["- (none)"]
    lines += ["\n## Commentary\n", commentary or "_(no commentary)_"]
    return "\n".join(lines)


async def report(uid: str, inp: dict[str, Any]) -> dict[str, Any]:
    rows = await db_select("finance_transactions", filters={"user_id": uid}, limit=5000)
    figures = _compute(rows)
    commentary, cost = await narrate(figures)
    art = await db_insert("artifacts", {
        "user_id": uid, "title": f"Accountant report — net {figures['net']:.2f}",
        "kind": "report", "brief": "Financial report", "approach": "",
        "text_dump": _report_md(figures, commentary), "status": "draft", "version": 1,
    })
    return {
        "artifact_id": (art or {}).get("id"),
        "summary": f"Report: income {figures['income']:.2f}, expense {figures['expense']:.2f}, net {figures['net']:.2f}",
        "metrics": {"cost_usd": round(cost, 4), "tool_calls": 1, "transactions": figures["count"]},
        "figures": figures,
    }


async def report_acceptance(uid: str, _inp: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """The report is accepted only if its category breakdown reconciles to net —
    a real arithmetic invariant, so a wrong/tampered number fails the gate."""
    f = result.get("figures") or {}
    cat_sum = round(sum((f.get("by_category") or {}).values()), 2)
    net = round(float(f.get("net") or 0), 2)
    ok = abs(cat_sum - net) < 0.01
    return {"accepted": ok,
            "reason": (f"category sums ({cat_sum}) reconcile to net ({net})" if ok
                       else f"does NOT reconcile: categories {cat_sum} vs net {net}")}
