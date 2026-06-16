# Liquidity Microstructure API

Standalone FastAPI service that streams L2 order books from any ccxt exchange
and serves real-time liquidity analytics. Algorithms extracted from
market-making bot patterns, re-implemented clean-room in typed Python.

## Algorithms

| Algorithm | Signal | Source concept |
|---|---|---|
| **Order book imbalance** | Directional pressure from bid/ask depth ratio within ±1% of mid | Order-flow analysis |
| **Liquidity wall detection** | Large resting orders (>3σ of level sizes) acting as support/resistance | Depth analysis |
| **Sweep detection** | Aggressive market orders clearing ≥3 levels between snapshots | Order-flow / momentum |
| **Dynamic spread estimation** | Volatility-adjusted fair spread (k·σ of mid returns) | Market-maker spread logic |
| **Composite liquidity score** | 0-100 market health (depth 50% + spread 30% + balance 20%) | MM venue assessment |

## Run

```bash
pip install fastapi uvicorn ccxt          # all already in WinnyWoo deps
uvicorn services.liquidity_api.app:app --port 8600
```

## Configuration (env vars)

| Var | Default | Meaning |
|---|---|---|
| `LIQ_EXCHANGE` | `binance` | ccxt exchange id |
| `LIQ_WATCHLIST` | `BTC/USDT,ETH/USDT,SOL/USDT` | comma-separated symbols |
| `LIQ_POLL_INTERVAL` | `5` | seconds between book polls |
| `LIQ_BOOK_DEPTH` | `100` | levels per side |
| `LIQ_IMBALANCE_BAND_PCT` | `1.0` | ±% band around mid for imbalance |
| `LIQ_WALL_SIGMA` | `3.0` | σ threshold for wall detection |
| `LIQ_SWEEP_MIN_LEVELS` | `3` | min levels cleared to flag a sweep |
| `LIQ_SWEEP_MIN_NOTIONAL` | `10000` | min USD notional consumed |
| `LIQ_API_KEY` | _(empty = no auth)_ | shared key checked via `X-Liquidity-Key` |
| `LIQ_HOST` / `LIQ_PORT` | `127.0.0.1` / `8600` | bind address |

## Endpoints

| Route | Returns |
|---|---|
| `GET /health` | engine status + watchlist |
| `GET /liquidity` | full analytics for all symbols |
| `GET /liquidity/BTC-USDT` | full analytics for one symbol |
| `GET /liquidity/BTC-USDT/signal` | condensed `{direction, strength}` signal |
| `GET /sweeps` | recent sweep events |

### Signal semantics (`/liquidity/{symbol}/signal`)

- `direction`: `bullish` / `bearish` / `neutral` — from depth imbalance
- `strength`: 0–1, boosted +0.25 by a confirming sweep, penalized −0.2 by a
  nearby opposing wall
- Treat as **context for the agents**, never as a sole entry trigger
  (walls can be spoofed; imbalance is a short-horizon signal)

## WinnyWoo integration paths

1. **Gateway analytics covariate** — ✅ WIRED. `gateway/analytics.py` fetches
   `/liquidity/{symbol}/signal` per pass (opt-in via `LIQUIDITY_API_URL`)
   and folds `liq_*` fields into the `trading_signals` indicators, nudging
   confidence ±(0.05/0.10) on confirming/opposing books.
2. **TradingAgents context** — the technical analyst prompt in
   `mcp-tradingagents` can embed the imbalance/walls/sweeps JSON as
   microstructure evidence. (not yet wired)
3. **Strategy** — ✅ WIRED. `winny/strategies/liquidity_microstructure.py`
   (`LiquidityMicrostructure`) is a full WinnyStrategy: backtestable
   bar-level sweep/pressure proxies for entries, plus this service as a
   live `confirm_trade_entry` veto (poor liquidity / wide spread / strong
   opposing book). Loader spec:
   `winny.strategies.liquidity_microstructure:LiquidityMicrostructure`
4. **TimesFM covariate** — feed the imbalance series as a covariate to
   `forecast_symbol` (SPECS.md supports `include_covariates`). (not yet wired)

## Caveats

- Poll-based (default 5 s), not websocket — adequate for the 1h-bar decision
  cadence of WinnyWoo; **not** an HFT tool.
- Walls are routinely spoofed on crypto venues. The signal endpoint already
  discounts them; never promote a wall to a hard entry/exit rule.
- One exchange per service instance. Run multiple instances (different
  `LIQ_PORT`) for cross-venue views.
