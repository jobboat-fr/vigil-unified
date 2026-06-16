"""mcp-algo — the engine + brokerage + (eventually) approval gate as MCP tools.

Per SPECS.md §3.3, this server exposes:
  - backtest               (PR #13 — this PR)
  - dry_run                (PR #13.5)
  - get_dry_run_status     (PR #13.5)
  - live_signal            (PR #13.5)
  - prepare_order          (PR #14)
  - submit_order           (PR #15, approval-gated)
  - cancel_order / cancel_all (PR #15)
  - get_portfolio / get_open_orders (PR #14)
  - get_market_context     (PR #14)

v1 ships only `backtest` — the only tool whose dependencies (engine, brokerage,
reference strategies, bar data) are fully present in the codebase today.
"""
