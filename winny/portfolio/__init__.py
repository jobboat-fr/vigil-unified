"""winny.portfolio — persistent portfolio state for the read-side tools.

The PortfolioStore is a WAL'd SQLite database that tracks:
  - Cash balances (per currency)
  - Open positions (per symbol, signed qty for long/short)
  - Pending/open orders awaiting fill

This store is the single source of truth for "what do I own right now?" between
MCP calls. It follows the same pattern as winny.common.audit: WAL mode,
synchronous=FULL, single in-process writer lock, survives restarts.

The store is **read** by PR #15 tools (get_portfolio, get_open_orders,
prepare_order) and **written** by PR #16 tools (submit_order, fill callbacks).

See also:
  - winny.portfolio.store — PortfolioStore class
  - winny.portfolio.snapshot — PortfolioSnapshot, PositionWithMTM value objects
"""
