"""Deterministic financial computations for the Finance department (Phase 2).

LLMs are unreliable at arithmetic, so every number a CFO would quote is computed
HERE, in Python — the model only narrates over the results. Clean-room implementations
of the standard formulas (no third-party code): P&L, balance sheet, cash flow, DCF
valuation, historical VaR, Benford's-law fraud screen, and variance analysis.

All functions are pure (no DB, no I/O) and unit-tested against known values.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any

# ── Statements (from the transaction ledger) ────────────────────────────────────
def pnl(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    """Income statement. Amounts are signed (income +, expense −)."""
    revenue = 0.0
    expense = 0.0  # accumulated as a positive magnitude
    by_category: dict[str, float] = {}
    for t in transactions:
        a = float(t.get("amount") or 0)
        if a >= 0:
            revenue += a
        else:
            expense += -a
        cat = t.get("category") or "uncategorized"
        by_category[cat] = round(by_category.get(cat, 0.0) + a, 2)  # signed; Σ == net_income
    net = round(revenue - expense, 2)
    return {
        "revenue": round(revenue, 2),
        "expense": round(expense, 2),
        "net_income": net,
        "net_margin": round(net / revenue, 4) if revenue else 0.0,
        "by_category": by_category,
    }


def balance_sheet(accounts: list[dict[str, Any]], transactions: list[dict[str, Any]]) -> dict[str, Any]:
    """Balances per account (Σ of its transactions), grouped by account type."""
    bal: dict[str, float] = {}
    for t in transactions:
        aid = t.get("account_id")
        if aid:
            bal[aid] = round(bal.get(aid, 0.0) + float(t.get("amount") or 0), 2)
    by_type: dict[str, float] = {"asset": 0.0, "liability": 0.0, "equity": 0.0, "income": 0.0, "expense": 0.0}
    for a in accounts:
        t = str(a.get("type") or "asset")
        by_type[t] = round(by_type.get(t, 0.0) + bal.get(a.get("id"), 0.0), 2)
    assets = round(by_type["asset"], 2)
    liabilities = round(abs(by_type["liability"]), 2)
    equity = round(by_type["equity"], 2)
    return {
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        # Retained earnings folds P&L into equity; identity is informational here
        # because the ledger isn't strict double-entry.
        "balances_balanced": abs(assets - (liabilities + equity)) < 0.01,
        "by_type": by_type,
    }


def cash_flow(transactions: list[dict[str, Any]]) -> dict[str, Any]:
    """Net cash movement and a monthly series (YYYY-MM)."""
    net = 0.0
    by_month: dict[str, float] = {}
    for t in transactions:
        a = float(t.get("amount") or 0)
        net += a
        m = str(t.get("txn_date") or "")[:7]
        if len(m) == 7:
            by_month[m] = round(by_month.get(m, 0.0) + a, 2)
    return {"net_cash": round(net, 2), "by_month": dict(sorted(by_month.items()))}


# ── Valuation & risk ─────────────────────────────────────────────────────────────
def dcf(cashflows: list[float], rate: float, terminal_growth: float | None = None) -> float:
    """Discounted cash flow NPV. Optional Gordon-growth terminal value on the last CF."""
    if rate <= -1:
        raise ValueError("discount rate must be > -1")
    npv = sum(float(cf) / ((1 + rate) ** i) for i, cf in enumerate(cashflows, start=1))
    if terminal_growth is not None and cashflows:
        if rate <= terminal_growth:
            raise ValueError("discount rate must exceed terminal growth")
        tv = float(cashflows[-1]) * (1 + terminal_growth) / (rate - terminal_growth)
        npv += tv / ((1 + rate) ** len(cashflows))
    return round(npv, 2)


def historical_var(amounts: list[float], confidence: float = 0.95) -> float:
    """Historical Value-at-Risk: the loss not exceeded with `confidence` probability,
    returned as a positive number (0 if the tail isn't a loss)."""
    xs = sorted(float(a) for a in amounts)
    if not xs:
        return 0.0
    pos = (1 - confidence) * (len(xs) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(xs) - 1)
    val = xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
    return round(-val, 2) if val < 0 else 0.0


# ── Fraud screen (Benford's law, first digit) ───────────────────────────────────
_BENFORD = {d: math.log10(1 + 1 / d) for d in range(1, 10)}


def _lead_digit(v: float) -> int | None:
    v = abs(float(v))
    if v == 0:
        return None
    while v < 1:
        v *= 10
    while v >= 10:
        v /= 10
    return int(v)


def benford(amounts: list[float]) -> dict[str, Any]:
    """First-digit conformity vs Benford's law. MAD with Nigrini thresholds; a high
    MAD flags amounts that may be fabricated/rounded (audit signal, not proof)."""
    digits = [d for d in (_lead_digit(a) for a in amounts) if d is not None]
    n = len(digits)
    expected = {str(d): round(_BENFORD[d], 4) for d in range(1, 10)}
    if n == 0:
        return {"n": 0, "observed": {}, "expected": expected, "mad": 0.0, "conformity": "n/a", "suspicious": False}
    counts = Counter(digits)
    observed = {d: counts.get(d, 0) / n for d in range(1, 10)}
    mad = sum(abs(observed[d] - _BENFORD[d]) for d in range(1, 10)) / 9
    if mad < 0.006:
        conformity = "close"
    elif mad < 0.012:
        conformity = "acceptable"
    elif mad < 0.015:
        conformity = "marginal"
    else:
        conformity = "nonconforming"
    return {
        "n": n,
        "observed": {str(d): round(observed[d], 4) for d in range(1, 10)},
        "expected": expected,
        "mad": round(mad, 4),
        "conformity": conformity,
        "suspicious": mad >= 0.015,
    }


# ── Variance (actual vs budget / prior period) ──────────────────────────────────
def variance(actual: dict[str, float], budget: dict[str, float]) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    total = 0.0
    for c in set(actual) | set(budget):
        a = round(float(actual.get(c, 0)), 2)
        b = round(float(budget.get(c, 0)), 2)
        v = round(a - b, 2)
        total += v
        rows[c] = {"actual": a, "budget": b, "variance": v, "pct": round((v / b) * 100, 2) if b else None}
    return {"by_category": rows, "total_variance": round(total, 2)}
