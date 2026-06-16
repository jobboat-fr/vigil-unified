"""mcp-winnywoo — Hermes-facing MCP server that exposes WinnyWoo state.

This MCP server is the bridge between the Hermes agent runtime (Kimi K2
brain, runs on OVH) and the WinnyWoo gateway (FastAPI, runs on Railway).
It lets Hermes answer questions about live trading state — portfolio,
positions, open orders, market quotes — and orchestrate trades through
the spec-mandated approval gate (Ed25519 + one-time code).

Wire shape:

    Hermes (Kimi K2)
        │
        │ tool call (stdio MCP)
        ▼
    mcp-winnywoo (this package)
        │
        │ HTTPS  /api/v1/*
        │ Authorization: Bearer <WW_SERVICE_TOKEN>
        ▼
    Railway gateway
        │
        ▼
    CCXT / Kraken / Coinbase / etc.

The service-token path on the gateway pins the caller identity to the
operator's email so owner-gated env-var brokerage credentials resolve.

Tools surfaced to Hermes:
    get_portfolio          NAV, balances, positions in one shape
    get_positions          open positions with MTM + uPnL
    get_open_orders        pending orders awaiting fill
    get_market_quote       last + bid/ask for a symbol
    propose_order          create an ApprovalRequest (does NOT submit)
    verify_approval        complete an approval with the one-time code
    cancel_order           cancel one open order
    cancel_all_orders      panic kill — cancel everything across brokers
    broadcast_event        push an envelope onto the gateway EventBus

See deploy/ovh/.env (WW_BACKEND_URL + WW_SERVICE_TOKEN) for required
runtime config.
"""
