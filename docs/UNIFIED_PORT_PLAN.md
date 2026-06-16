# VIGIL × WinnyWoo — Full Native Port into `vigil-unified`

**Goal (user-chosen):** rebuild **everything** VIGIL and WinnyWoo do **natively inside `vigil-unified`** — as the Hermes runtime + one product backend + Hermes plugins/MCP/skills. **No remote Railway calls.** The deployed Railway services become reference implementations we port, not dependencies.

> This is a multi-stage program. Each stage lands runnable value and is checked off below. Newest notes at the bottom of each stage.

---

## 0. Source map (where the truth currently lives)

| Capability | Today (source) | Language | Lands in `vigil-unified` |
|---|---|---|---|
| Agent runtime, chat, skills, tools, cron, dashboard | `vigil-unified` itself (Hermes fork) | Python | already here |
| Trading engine (brokers, strategies, forecast, portfolio, reasoning) | `winny woo/winny/` | Python | `winny/` (vendor as-is) |
| Product API (signals, orders, approvals, portfolio, market, audit, vault, settings, broker-connect, billing, account, ws, events, agents, backtest, auto-trade, onboarding, assistant, integrations) | `winny woo/gateway/` (FastAPI, live on Railway) | Python | `winny_gateway/` (vendor, rename pkg) |
| Trading MCP servers (algo, approval, timesfm, tradingagents, winnywoo) | `winny woo/winny/mcp/` | Python | `winny/mcp/` (vendor as-is; console scripts) |
| Liquidity service | `winny woo/services/liquidity_api/` | Python | `services/` (vendor) |
| Meeting Room, Council, Deal Board, avatar (Tavus/BeyondPresence), LiveKit pipeline, STT/TTS, Hume emotion, learning, exports, intervention, guest rooms | `VIGIL/backendv2/src/modules/meeting-room/` + `VIGIL` vigil-core | Node/Express | **port to Python** → `winny_gateway/routes/vigil/` + `winny/council/` |
| Studio / Artifacts | `VIGIL/backendv2/src/modules/studio/` | Node | port → `winny_gateway/routes/vigil/studio.py` |
| Finance (cfoStack / C.L.E.A.R.) | `VIGIL .../modules/finance/` + azzco cfoStack | Node | port → `winny/finance/` + skills/finance |
| Mail (triage, templates, send) | `.../modules/mail/` | Node | port → `winny_gateway/routes/vigil/mail.py` |
| Operations control-plane, orgs, observability | `.../modules/operations/` | Node | port → `winny_gateway/routes/vigil/operations.py` |
| Behavioral / memory / learning loop | `.../modules/behavioral|memory|learning/` | Node | port → reuse Hermes memory + `winny_gateway` routes |
| VIGIL-as-MCP server | `.../modules/integrations/mcp/vigil-mcp-server.routes.js` | Node | superseded by Hermes `mcp_serve.py` + plugins |

**Shared spine (unchanged):** Supabase (one JWT, storage key `vigil-auth`), `{ ok, data }` envelope.

---

## 1. Target architecture inside `vigil-unified`

```
vigil-unified/
  agent/ run_agent.py hermes_cli/ gateway/   # Hermes runtime (UNCHANGED) — messaging gateway, dashboard :9119
  winny/                # vendored trading engine (pkg name unchanged — no collision)
    mcp/                # algo, approval, timesfm, tradingagents, winnywoo (console scripts)
  winny_gateway/        # vendored WinnyWoo FastAPI gateway, RENAMED from `gateway` to avoid
                        # collision with Hermes gateway/. Serves /api/v1/* + /v1/vault/* + /health on :8400
    routes/             # existing WinnyWoo routers
    routes/vigil/       # NEW: ported VIGIL routers (rooms, council, studio, mail, operations)
  services/             # vendored liquidity_api
  plugins/
    winnywoo/           # NEW Hermes plugin → trading tools (signals, market, submit-order-with-approval, portfolio)
    vigil/              # NEW Hermes plugin → council, studio, vault, meeting tools
  skills/               # mined skills (thinking/ done; finance/marketing/crm/mail in progress)
  web/                  # single frontend — clients repointed to LOCAL backends
    src/lib/ww.ts       # → http://127.0.0.1:8400  (was Railway)
    src/lib/vigil.ts    # NEW client → same gateway /v1/* (VIGIL routers)
    src/lib/api.ts      # → Hermes dashboard :9119 (unchanged)
```

**Two local processes (dev):** (a) Hermes dashboard `:9119` (agent/chat/skills/sessions), (b) `winny_gateway` `:8400` (all product APIs). The web app talks to both. The gateway proxies chat to Hermes via `HERMES_URL=http://127.0.0.1:9119`. No Railway.

**Naming decision:** vendor the FastAPI gateway as top-level package **`winny_gateway`** (repath `gateway.` → `winny_gateway.` inside the vendored copy only). `winny`, `services` keep their names (no collision).

---

## 2. Dependency strategy

Add a `[project.optional-dependencies] product` extra to `vigil-unified/pyproject.toml` with winny's runtime deps (`polars, duckdb, pyarrow, keyring, python-ulid, supabase, stripe, pypdf, ccxt`, plus `numpy` already core-ish). Heavy ML (`torch/timesfm/transformers`) stays in a separate `forecast` extra (only on hosts running mcp-timesfm). Install with `pip install -e .[product]`. Keeps the base Hermes install lean (supply-chain blast radius rule in pyproject).

---

## 3. Stages (checklist)

### Stage 1 — Vendor the WinnyWoo Python backend (tractable half) ✅ DONE
- [x] Copied `winny/` (100 .py, engine + MCP servers) + `services/` → repo root (no import changes).
- [x] Copied `gateway/` → `winny_gateway/` (39 .py); repathed `from gateway.` → `from winny_gateway.` + the uvicorn module string. No functional `gateway.` refs remain (only log-string cosmetics).
- [x] Added `[product]` + `[forecast]` extras + 5 `mcp-*` console scripts + packages.find entries to pyproject. `pip install -e .[product]` OK (ccxt, polars, duckdb, supabase, stripe, pypdf…).
- [x] Launcher `python -m winny_gateway` boots on `127.0.0.1:8400`. `/health` → ok. `/api/v1/market/overview` returns **real live data** (Coinbase BTC price + Fear&Greed) with no Railway.
- [x] Web: `ww.ts` base → local `:8400` default, Railway hardcode removed. (Re the earlier audit: the `/v1/vault` vs `/api/v1/...` split is **correct by design** — vault router is `/v1/vault`, trading is `/api/v1/*`; not a bug.)
- **Caveat:** `mcp-algo`/`mcp-approval` run in stub mode locally because the venv `Scripts/` dir isn't on the spawned subprocess PATH (and `timesfm`/`tradingagents` are intentionally disabled — need torch/langgraph). Routes that don't need MCP (market, vault, signals, audit) work fully. Real MCP = Stage 2 (fix PATH / use `python -m`).

### Stage 2 — Hermes plugins/skills for the trading side ✅ DONE
- [x] **Cross-platform MCP fix:** vendored `winny/mcp/base.py` used `asyncio.connect_read_pipe(stdin)` which crashes on Windows (Proactor `recv_into` on a non-socket) → stdio handshake silently timed out (30s). Switched to a thread-backed `sys.stdin.buffer.readline`. Verified: `initialize` now answers instantly. Also: gateway spawns `algo`/`approval` via `sys.executable -m winny.mcp.<name>.server` (PATH-independent); bridge `start()` broadened to degrade any failing server to stub instead of crashing.
- [x] `plugins/winnywoo/` Hermes plugin (`kind: backend`, auto-load): tools `ww_market`, `ww_signals`, `ww_portfolio`, `ww_approvals`, `ww_audit`. Thin client follows the `WW_BACKEND_URL`/`WW_SERVICE_TOKEN`/`X-WinnyWoo-User-Id` convention; `unwrap()` peels both the `{ok,data}` REST envelope and the MCP `{content:[{text}]}` passthrough. **Read-only by design** — order execution stays behind the human approval gate (agent proposes, human disposes via dashboard).
- [x] Verified end-to-end vs the live local gateway: `ww_market` → real Coinbase/Fear&Greed data (public); `ww_portfolio` → real snapshot via the `algo` MCP over stdio (service-token auth); `ww_approvals`/`ww_audit` degrade gracefully without Supabase.
- [~] Skill routing (finance/marketing → Trade Desk/Signals/Calculations) is tracked in `UNIFIED_BUILD_LOG.md` and wired as each product flow is built — not blocking the port.

### Stage 3 — Port VIGIL Meeting Room + Council (Node → Python) ✅ DONE (core)
- [x] `winny/council/` — faithful Python port of VIGIL's council: `providers.py` (Anthropic/OpenAI/Gemini + OAI-compat, async httpx, **graceful offline stubs** when keys absent), `scoring.py` (JSON extract + weighted rubric), `registry.py` (4 workers across 3 families + 4 task lenses + role prompts), `collective.py` (5-stage orchestrate: primary → parallel reviewers → weighted consensus → chairman-on-disagreement → verdict/totals). Behavioral 572-pattern overlay is an optional hook (deferred).
- [x] `winny_gateway/routes/vigil/council.py` — `GET /v1/council/tasks`, `POST /v1/council/orchestrate`, `POST /v1/council/orchestrate/stream` (SSE). `rooms.py` — room CRUD, Deal Board members, transcript, `GET /v1/rooms/:id/stream` SSE that convenes the council over the transcript. Mounted in `app.py`. Verified end-to-end over HTTP (tasks, orchestrate, room create/member/message, SSE: `start→primary_done→reviewer_done×2→consensus_result→complete`).
- [x] Web: `web/src/lib/vigil.ts` client (mirrors `ww.ts`; fetch-based SSE reader since EventSource can't send the bearer). `MeetingRoomPage` rewritten from scaffold → real UI (rooms list, Deal Board advisor chips, transcript capture, per-lens Convene with live stage stream + verdict card). `tsc --noEmit` passes.
- [~] **Deferred — avatar/voice (3e):** Tavus/BeyondPresence avatars, ElevenLabs TTS, Whisper STT, LiveKit token mint, Hume emotion. Not built: nothing calls them yet and the text council is the core. To add later as `winny_gateway/routes/vigil/avatar.py` + voice pipeline behind provider keys.

### Stage 4 — Port Studio / Artifacts + Vault grounding
- [ ] `winny_gateway/routes/vigil/studio.py` — artifact CRUD, from-room crystallize, artifact chat. Web: wire `StudioPage`.
- [ ] Vault: confirm `vault.py` parity (it's already in the gateway) + wire search.

### Stage 5 — Finance, Mail, Operations control-plane
- [ ] `winny/finance/` cfoStack (C.L.E.A.R.) port; finance report build. New page + skill wiring.
- [ ] `winny_gateway/routes/vigil/mail.py` — templates/preview/send/triage (mailpile skills).
- [ ] `winny_gateway/routes/vigil/operations.py` — orgs, members, monitor-events, observability.

### Stage 6 — Unify persona, plugins/vigil, end-to-end
- [ ] `plugins/vigil/` Hermes plugin: council/studio/vault/meeting tools so the agent drives them.
- [ ] Bake global skills (`verification-before-completion`, `systematic-debugging`, brainstorm-first) into SOUL.md/AGENTS.md.
- [ ] One-command dev up (both servers); E2E: chat → council → artifact → vault; trade signal → approval → order.

---

## 4. Risks / decisions

- **Node→Python port (Stages 3–5)** is the bulk and highest risk: meeting-room is the largest VIGIL module (LiveKit/Tavus/ElevenLabs/Hume). Port behavior, not line-by-line; keep the same REST/SSE contract the web already expects (`/v1/rooms/*`) so the frontend is a drop-in.
- **Provider keys** (Anthropic/OpenAI/Gemini, LiveKit, Tavus, ElevenLabs, Hume, broker keys, Supabase) are required for full function — these are provider integrations, not Railway. Features degrade gracefully without them.
- **Single source of truth for writes:** MCP servers (algo/approval) remain authoritative for trades; gateway is the REST/WS facade.

---

## 5. Build log
- 2026-06-15 — Deep discovery of all three repos complete. Architecture + stages defined (this doc). Starting Stage 1.
- 2026-06-15 — **Stage 1 complete.** WinnyWoo Python backend (`winny/` + `winny_gateway/` + `services/`) vendored natively into vigil-unified, deps wired into pyproject (`[product]`/`[forecast]` + mcp scripts), gateway runs locally on :8400 serving real market data, web `ww.ts` repointed to local. Hermes dashboard (:9119) + product gateway (:8400) now both run with zero Railway dependency.
- 2026-06-15 — **Stage 2 complete.** Fixed a real Windows MCP stdio bug in `winny/mcp/base.py` (thread-backed stdin read) so `algo`/`approval` MCP servers work cross-platform; gateway now spawns them via the current interpreter. Built `plugins/winnywoo/` (5 read/observe desk tools) and verified the full agent→gateway→MCP chain returns real data (market public, portfolio via service token). Order execution intentionally kept behind the human approval gate.
- 2026-06-15 — **Stage 3 complete (core).** Ported VIGIL's AI Council (Node→Python) into `winny/council/` — multi-provider client with offline stubs, score parser, worker/task registry, and the 5-stage orchestrator. Added `/v1/council/*` and `/v1/rooms/*` routers (incl. SSE) to the gateway, a `vigil.ts` web client with a bearer-capable SSE reader, and a real `MeetingRoomPage` (Deal Board + transcript + live council stream + verdict). Verified end-to-end (HTTP + SSE) and `tsc --noEmit`. Avatar/voice/LiveKit deferred. Next: Stage 4 (Studio/Artifacts + Vault wiring).
