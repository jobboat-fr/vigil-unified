# VIGIL — Engineering Handoff (the onboarding bible)

_Current 2026-06-24. Everything the next dev team needs: repos, folder maps,
runtime architecture, the domain/business logic, the algorithms, the data model,
deploy, testing, migration, and open items. Skim §0 then jump._

---

## 0. TL;DR

VIGIL is a **multi-tenant "agentic company" SaaS**. Each tenant runs autonomous AI
**departments** on an **effectiveness contract**, plus a deliberating **AI council /
meeting room**, a human-in-the-loop **crypto trade desk**, and **finance / CRM / mail /
vault / studio** surfaces. The product is **human-in-the-loop**: anything that moves
money or sends a message is **owner-gated**.

It runs across **3 runtimes + 1 managed DB**, from **2 git repos**:
- **`vigil-unified`** (this repo) → **Vercel** (frontend SPA) + **Railway** (gateway API).
- **`winny woo`** (`../winny woo`, remote `jobboat-fr/WinnyWoo`) → **OVH VPS** (Hermes
  operator dashboard, dashboard plugins, Google-Meet bot, LiveKit agent, Caddy gate).
- **Supabase** (`pqikzrcykdynxhtnjgeh`) = all product data, RLS-scoped `auth.uid()=user_id`.

**Deploy = `git push origin main`** (Vercel + Railway auto-deploy). NOT `npx vercel` (no-ops).

---

## 1. Repos & local folders

### 1a. `vigil-unified` (frontend + product gateway + council engine)
A fork of the Hermes agent that also carries the product code. Top-level:

```
vigil-unified/
├─ web/                     # Vite + React SPA → VERCEL (dev.vigil-ai.xyz)
│  ├─ src/
│  │  ├─ App.tsx            # app shell: grouped sidebar nav, routing, chat host
│  │  ├─ pages/  (38)       # one per route (OpsTeamPage, MeetingRoomPage, TradeDeskPage, …)
│  │  ├─ components/        # AuthGate, AuthWidget, BrandLoader, OnboardingWizard, EmptyState, LiveRoom, ChatSidebar, …
│  │  ├─ context/ contexts/ # AuthContext (Supabase), ProfileProvider, PageHeader, SystemActions
│  │  ├─ lib/               # api.ts (operator proxy client), vigil.ts (product API client),
│  │  │                     #   ww.ts (trade/market), supabase.ts, brand.ts (design tokens), seo.ts
│  │  ├─ plugins/           # dashboard-plugin loader (usePlugins, registry, slots)
│  │  ├─ themes/  i18n/(20) # theme presets + 20-locale i18n
│  │  └─ index.css          # Hermes LENS_0 palette (teal #041c1c / cream #ffe6cb) + fonts
│  ├─ api/ops.js            # Vercel serverless: Supabase-gated reverse proxy → OVH (+ /dashboard-plugins/*)
│  ├─ vercel.json           # rewrites (/api → ops, SPA fallback) + CSP headers
│  └─ index.html            # SEO meta/OG/JSON-LD
├─ winny_gateway/           # FastAPI product API → RAILWAY (winnywoo-production.up.railway.app)
│  ├─ app.py                # builds the FastAPI app, includes ~30 routers, middleware order
│  ├─ auth.py               # Supabase JWT validation (ES256 via JWKS) → get_current_user
│  ├─ db.py                 # Supabase client + db_insert/select/update/delete; _USER_SCOPED_TABLES
│  ├─ security.py           # body cap, sliding-window rate limit (XFF-safe), security headers
│  ├─ logging.py            # structured JSON logger (get_logger, extra={action,component,…})
│  ├─ ops/                  # THE AGENTIC COMPANY (see §4)
│  │  ├─ engine.py          #   department registry + run_job (the effectiveness contract)
│  │  ├─ support/finance/revenue/marketing/growth/legal/operations/cos.py  # the 8 departments
│  │  ├─ finance_calc.py    #   deterministic finance math (DCF/VaR/Benford/PnL)
│  │  ├─ brand.py           #   brand-voice QA gate (consensus)
│  │  └─ billing.py         #   plans / usage metering / quota (Phase 7)
│  ├─ integrations/         # connector kit (see §5)
│  │  ├─ connector.py       #   Connector ABC + generic encrypted store + owner-gated actions
│  │  ├─ github/hubspot/stripe_conn/gmail/notion/plaid_client.py  # providers
│  │  ├─ hermes_dispatch.py #   Phase-6 gateway→OVH skill dispatch (opt-in, graceful)
│  │  └─ secrets.py         #   Fernet encrypt/decrypt + masking
│  ├─ routes/vigil/         # product routers: ops, connect, rooms, council, finance, crm, mail, studio, privacy, finance_connect
│  └─ migrations/           # 008–022 SQL (ops_team, connections, outbound_actions, legal_precedents, …)
├─ winny/                   # the council + trading engine (imported by the gateway)
│  ├─ council/              # collective.py (5-stage), consensus.py, intervention.py, scoring.py,
│  │                        #   providers.py (ask/ask_cheap), registry.py (worker pools), summarizer.py, structurer.py
│  ├─ forecast/ models/     # TimesFM + statistical fallback, markov, …
│  ├─ data/                 # market data providers (CCXT public, CryptoCompare)
│  ├─ engine/ strategies/ portfolio/ brokerage/ coinbase/  # trading desk internals
│  └─ reasoning/ agents/    # reasoning helpers, agent adapters
├─ hermes_cli/ agent/ gateway/ acp_adapter/ cron/ hermes_*.py   # inherited Hermes-agent core (the base fork)
├─ tests/winny_gateway/     # hermetic pytest suite (94 tests) — FakeDB + monkeypatched LLMs
└─ plans/                   # agentic-company-master-plan.md, architecture-review.md, plugins-skills-harvest.md
```

### 1b. `winny woo` (OVH operator side) — `../winny woo`, remote `jobboat-fr/WinnyWoo`
The Hermes operator dashboard + plugins that run on the OVH VPS.
```
winny woo/
├─ hermes/plugins/          # dashboard plugins (served at /dashboard-plugins/*)
│  ├─ google_meet/          #   the Meet bot: meet_bot.py (Playwright join/knock/lobby),
│  │  ├─ realtime/openai_client.py     #   OpenAI-Realtime TTS (fallback voice)
│  │  ├─ realtime/elevenlabs_client.py #   ElevenLabsSpeaker (the bot's voice; pcm_24000) ← added
│  │  └─ audio_bridge.py / process_manager.py / tools.py
│  ├─ kanban/ hermes-achievements/ memory/ browser/ image_gen/ video_gen/ dashboard_auth/ …
├─ deploy/ovh/             # Caddyfile (gate lanes), docker-compose.yml, hermes_server.py (shim), bootstrap.sh
├─ gateway/ winny/ hermes/ # (overlapping fork code — OVH-side variants)
├─ vigil-web/ vigil-agents/ mobile/ services/  # other surfaces
└─ supabase/               # SQL the OVH side references
```
> Note: both repos descend from the same Hermes fork, so `gateway/`, `winny/`, `hermes/`
> names appear in both. **Authoritative deploy targets:** product gateway = `vigil-unified/winny_gateway` (Railway); operator dashboard/bot = `winny woo/hermes` (OVH).

---

## 2. Runtime topology & request/auth flow

```
Browser (dev.vigil-ai.xyz, Vite SPA)
  │  Supabase session (storage key "vigil-auth")
  ├─ product data  → fetch winnywoo-production.up.railway.app  (Bearer Supabase JWT)
  │                     → gateway auth.py validates ES256 via JWKS → routes (RLS via service role, user_id-scoped)
  │                        → Supabase  (pqikzrcykdynxhtnjgeh)
  └─ /api/*  (operator console, chat, plugins)
        → Vercel web/api/ops.js  (verifies the Supabase session)
            → OVH Hermes dashboard behind Caddy  (injects x-ops-gate=OPS_GATE_SECRET + scraped
               window.__HERMES_SESSION_TOKEN__; refresh-on-401)
            → /api/dashboard-plugins/*  served by the same ops.js branch (correct MIME)
```
- **Two auth systems:** product = Supabase (AuthContext); operator console = the OVH gate,
  reached only through the Supabase-gated proxy. One product login lights up both.
- **Logout** (`AuthContext.signOut`) tears down the operator session (clearHermesSession) **then**
  `supabase.auth.signOut()`. `AuthWidget` renders the logout for product users too.

---

## 3. Business logic (the domain)

### 3a. The Ops Team — agentic company (`winny_gateway/ops/`)
8 departments, each a **spec** in `engine.py::DEPARTMENTS` with: `slug`, `head_lens`,
`mandate`, `kpis`, `sync_kinds` (which connector kinds to pre-sync), `guardrails`
(per-run $ cap, daily cap, allowed tools, wall-ms, irreversible-requires-owner), and
`jobs` (each job = `handler` + deterministic `acceptance` + `default_input` + `is_selftest`).

Departments: **support** (inbox triage), **finance** (reconcile/report/analyze), **revenue**
(stalled-deal follow-ups), **marketing** (campaigns), **growth/Lead-Scout** (source leads →
hand off to revenue), **legal** (grounded doc review), **operations** (open-items digest),
**cos/Chief-of-Staff** (routes the whole company + executive brief).

**`run_job()` — the effectiveness contract (the core algorithm):**
1. resolve dept spec + job (None → primary job); reject unknown.
2. **guardrails** before any spend: paused? daily cap reached?
3. insert `ops_tasks` row (status=working).
4. **pre-sync** connectors for the dept's `sync_kinds` (concurrent, best-effort).
5. run handler — **Phase-6**: if `job.hermes_skill` and `hermes_dispatch.available()`, dispatch to OVH; on any failure fall back to the local handler.
6. run **deterministic acceptance** (an arithmetic/grounding invariant — NOT an LLM "looks good").
7. **budget enforcement**: over per-run $ cap or wall-ms → `blocked`, not a slow success.
8. record task + `ops_events` activity + recompute `compute_health` (success_rate, p50, runs).
9. **handoffs**: an accepted run may hand work to other departments, **depth-bounded** (`MAX_HANDOFF_DEPTH=2`) so fan-out can't loop. (cos→scout→revenue.)

### 3b. Connector kit (`integrations/connector.py`)
`Connector` ABC: `verify_token`, `sync`, `supported_actions`, `act`. Generic `connections`
table stores **per-tenant tokens encrypted with Fernet** (platform OAuth creds stay in env,
never per-tenant). `sync_kind(uid, kind)` syncs all of a tenant's connections of a kind
**concurrently**. **Owner-gated writes:** `propose_action` (agent, inserts PENDING, never
executes) → `approve_action` (human → executes via `c.act`) → `reject_action`. Providers:
GitHub, HubSpot, Stripe, Gmail (IMAP app-password), Notion (→ commitments), Plaid.

### 3c. Meeting lifecycle (`routes/vigil/rooms.py`)
Create room → invite advisors (Deal Board) → capture transcript / live LiveKit room +
optional Tavus avatar or Google-Meet bot → **End meeting** → `summarize` (persists the
summary on the room, marks it closed, **makes the AI agent leave** via `_end_room_agent`) →
**council convenes over the SUMMARY only** (`source=summary`) for token economics — the LLMs
never see the full transcript. Live-advisor "raise hand" runs the intervention engine on a
heartbeat.

### 3d. Commercial model (`ops/billing.py`, Phase 7)
Mirrors VIGIL's `plans`/`subscriptions`/`org_members`/`usage_events`/`usage_quotas`.
`tenant_plan(uid)` resolves org→subscription tier; usage derived from `ops_tasks`;
`check_run_quota` → 429 when the daily run cap is hit. GDPR export/erase in `privacy.py`.

---

## 4. Algorithms (the interesting bits)

- **Council 5-stage collective** (`winny/council/collective.py`): primary advisor → parallel
  reviewers score → consensus → chairman synthesis → behavioral overlay → verdict
  (readiness score, consensus_reached).
- **Consensus panel** (`council/consensus.py`): N council workers vote yes/no on a strict
  question; weighted tally vs a threshold (0.66). Offline workers **abstain** (don't skew);
  empty panel → no verdict (caller falls back). Used by Legal's verify + brand QA.
- **Cheap-tier failover** (`council/providers.py::ask_cheap` + `registry.cheap_pool`): a pool
  of cheap models with a 120s rate-limit cooldown ledger; falls back to the primary.
- **Intervention "raise hand"** (`council/intervention.py`): specialist fan-out → judge →
  behavioral overlay weighted by per-tenant `pattern_weights` (cooldown, min-signals, silence-bias).
- **Finance math** (`ops/finance_calc.py`, clean-room, unit-tested to known values): `pnl`,
  `balance_sheet`, `cash_flow`, `dcf(cashflows, rate, terminal_growth)`,
  `historical_var(amounts, confidence)`, `benford` (Nigrini MAD fraud signal), `variance`.
  Acceptance checks are arithmetic invariants (category sums reconcile to net).
- **Acceptance invariants**: Legal = grounded in REAL cited `[doc:<id>]` + consensus confidence;
  Operations = recount reconciles; Marketing = audience = `crm_contacts` count; Finance report =
  `by_category` sums to `net_income`.
- **Forecast** (`winny/forecast`): TimesFM 2.5 when available, else a labelled drift+vol
  statistical fallback; keyless CCXT public OHLCV by default.

---

## 5. Data model (Supabase, ~105 tables) — the ones that matter

| Domain | Tables |
|---|---|
| Auth/tenancy | `app_users`, `profiles`, `organizations`/`orgs`, `org_members`, `user_preferences` |
| Ops Team | `departments`, `ops_tasks`, `ops_events`, `ops_jobs` |
| Connectors | `connections` (encrypted tokens), `outbound_actions` (owner-gated), `integration_secrets`, `integration_audit_log` |
| Meetings/council | `rooms` (transcript jsonb, summary, status, live_*), `meetings`, `meeting_*`, `room_messages`, `ai_interventions`, `pattern_weights`, `council_votes`, `commitments` |
| Finance/CRM/Mail | `finance_transactions`/`accounts`/`connections`, `crm_contacts`, `crm_deals`, `mail_messages`, `mail_drafts` |
| Studio/Vault | `artifacts`, `artifact_versions`, `studio_sessions`, `vault_documents` |
| Trading | `trading_signals`, `approval_requests`, `broker_credentials`, `auto_trade_config`, `portfolio_snapshots` (note: `trade_history` is DEAD — broker is source of truth) |
| Commercial | `plans`, `subscriptions`, `usage_events`, `usage_quotas`, `legal_precedents` |
| Audit/security | `audit_events`, `activity_events`, `blocked_ips`, `security_incidents`, `deletion_requests` |

Every product table is **RLS-scoped** to `auth.uid()`; the gateway also filters `user_id=uid`
at the route layer (defense-in-depth — see `tests/.../test_ops_tenant_isolation.py`).

---

## 6. Frontend architecture (`web/`)
- **Shell** `App.tsx`: sidebar grouped into **Workspace / Company / Trade Desk / Insight /
  System**; persistent ChatPage host (PTY survives tab switches); plugin nav; collapse.
- **Auth gate** `AuthGate` → `PublicSite` (landing/docs/login) when logged out, else the app.
- **Design system**: Hermes LENS_0 — teal `#041c1c` + cream `#ffe6cb` + amber `#ffbd38` +
  emerald; fonts Mondwest (display), Collapse/RulesCompressed, JetBrains Mono. Tokens in
  `index.css` + shared `lib/brand.ts`. `@nous-research/ui` for primitives.
- **API clients**: `lib/vigil.ts` (product gateway), `lib/api.ts` (operator proxy + SSE),
  `lib/ww.ts` (trade/market). All inject the Supabase Bearer; ops proxy gates on it.
- **CX**: `OnboardingWizard` (first-run, live checklist), `BrandLoader`, `EmptyState`/`Skeleton`.

---

## 7. Deploy, env, testing

**Deploy** (see also `curl` smoke checks):
```bash
git push origin HEAD:main      # → Vercel (frontend) + Railway (gateway)
# OVH (winny woo): ssh → chown ubuntu:ubuntu /opt/winnywoo → git pull → docker compose up -d --force-recreate
```
**Tests:** `.venv/Scripts/python.exe -m pytest tests/winny_gateway/ -p no:cacheprovider -o addopts="" -q` (94, hermetic). Frontend: `cd web && npx tsc -b --force`.

**Env / secrets (key names; values in platform dashboards):**
- Vercel: `OPS_DASHBOARD_URL`, `OPS_GATE_SECRET`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `VITE_SITE_URL`.
- Railway: Supabase URL+service-role, Fernet secret, `OPS_DASHBOARD_URL`+`OPS_GATE_SECRET`, `DEFAULT_OPS_PLAN`, broker/LLM keys.
- OVH `.env`: `OPS_GATE_SECRET` (match Vercel), LiveKit, Tavus, **ElevenLabs (`ELEVENLABS_API_KEY`,`ELEVENLABS_VOICE_ID`,`ELEVENLABS_MODEL_ID`)**, OpenAI, HF, Supabase service-role.

---

## 8. Migrating to a new VPS
Safe — data is in Supabase (managed); Vercel/Railway are PaaS. Only the **OVH box** moves. Must handle:
1. OVH IP is encoded in `vigil-ops-<ip>.nip.io` → new IP → update `OPS_DASHBOARD_URL` (Vercel) + Caddy host.
2. `OPS_GATE_SECRET` must match Vercel ↔ Caddy. 3. Carry `.env`. 4. `chown ubuntu:ubuntu`.
5. **Recreate** Caddy (don't reload — bind-mount inode trap). 6. Session token self-heals.

---

## 9. Open items / gotchas
- **Deploy via git push, NOT `npx vercel`** (CLI deploys don't alias to prod — wasted hours once).
- **OVH Winston (Node) logging** — not done (separate repo, unbuildable here). Plan: add `winston` + `src/logger.ts` to the Node TUI app.
- **In-app activity-logs view** — gateway emits structured logs (Railway aggregator); Ops feed shows dept activity; a unified product page is TODO.
- **ElevenLabs Meet voice** — set the env on OVH + redeploy to flip from the OpenAI-Realtime fallback.
- **OAuth-broker connectors** (QuickBooks/Square/DocuSign/Outreach/Box) — batch behind one shared OAuth callback service.
- **Secret rotation** (launch blocker) — rotate keys exposed in chat history.
- **Frontend bundle** ~2.8 MB single chunk — code-split for LCP; full SSR/prerender for `/` and `/docs` is still pending (meta/OG/sitemap shipped).
- `web/index.html` SEO base URL + `OPS_DASHBOARD_URL` hard-code the current `dev.vigil-ai.xyz` / nip.io host — update on domain change.

---

## 10. Where to look first
`plans/agentic-company-master-plan.md` (the why) · `winny_gateway/ops/engine.py` (the contract) ·
`winny_gateway/integrations/connector.py` (the kit) · `winny/council/collective.py` (the council) ·
`web/src/App.tsx` (the shell) · `web/api/ops.js` (the proxy) · `tests/winny_gateway/` (behavior spec).
