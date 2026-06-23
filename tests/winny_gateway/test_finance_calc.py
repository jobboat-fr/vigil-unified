"""Pure-math tests for finance_calc — known values, deterministic. This is the
'numbers computed, not guessed' guarantee."""
from __future__ import annotations

import math

from winny_gateway.ops import finance_calc as fc


def test_pnl_and_reconcile_invariant():
    txns = [
        {"amount": 1000.0, "category": "revenue"},
        {"amount": -300.0, "category": "software"},
        {"amount": -200.0, "category": "office"},
    ]
    p = fc.pnl(txns)
    assert p["revenue"] == 1000.0 and p["expense"] == 500.0 and p["net_income"] == 500.0
    assert p["net_margin"] == 0.5
    # the load-bearing invariant: signed category sums equal net income
    assert round(sum(p["by_category"].values()), 2) == p["net_income"]


def test_balance_sheet_groups_by_account_type():
    accounts = [{"id": "a1", "type": "asset"}, {"id": "l1", "type": "liability"}]
    txns = [{"account_id": "a1", "amount": 500.0}, {"account_id": "l1", "amount": -200.0}]
    bs = fc.balance_sheet(accounts, txns)
    assert bs["assets"] == 500.0 and bs["liabilities"] == 200.0 and bs["equity"] == 0.0


def test_cash_flow_by_month():
    txns = [
        {"amount": 100.0, "txn_date": "2026-05-10"},
        {"amount": -40.0, "txn_date": "2026-05-20"},
        {"amount": 25.0, "txn_date": "2026-06-01"},
    ]
    cf = fc.cash_flow(txns)
    assert cf["net_cash"] == 85.0
    assert cf["by_month"] == {"2026-05": 60.0, "2026-06": 25.0}


def test_dcf_known_value():
    assert fc.dcf([100, 100, 100], 0.10) == 248.69          # 90.91 + 82.64 + 75.13
    assert fc.dcf([100], 0.10, terminal_growth=0.02) == 1250.0


def test_dcf_guards():
    import pytest
    with pytest.raises(ValueError):
        fc.dcf([100], 0.05, terminal_growth=0.10)            # growth ≥ rate


def test_historical_var():
    amounts = [-100, -50, -20, -10, 0, 10, 20, 50, 100, 200]
    assert fc.historical_var(amounts, 0.90) == 55.0
    assert fc.historical_var([10, 20, 30], 0.95) == 0.0      # no loss tail


def test_benford_flags_fabricated_amounts():
    expected_d1 = round(math.log10(2), 4)
    fake = [9, 90, 900, 9000, 95, 99, 9999]                  # all leading 9 — fabricated
    b = fc.benford(fake)
    assert b["expected"]["1"] == expected_d1
    assert b["observed"]["9"] == 1.0
    assert b["conformity"] == "nonconforming" and b["suspicious"] is True


def test_benford_empty_is_safe():
    b = fc.benford([0, 0])
    assert b["n"] == 0 and b["suspicious"] is False


def test_variance_actual_vs_budget():
    v = fc.variance({"sales": 120, "ops": 80}, {"sales": 100, "ops": 100})
    assert v["by_category"]["sales"]["variance"] == 20.0
    assert v["by_category"]["sales"]["pct"] == 20.0
    assert v["total_variance"] == 0.0
