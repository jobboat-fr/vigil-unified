# Architecture & business-logic review

_A standing review of the VIGIL × WinnyWoo platform: topology, what's solid, and the
ranked gaps worth closing. Pairs with [`plans/plugins-skills-harvest.md`](plugins-skills-harvest.md)
(connector roadmap) and the agentic-company master plan._

## Topology (three runtimes)

```
Browser (Vite SPA, dev.vigil-ai.xyz)
  ├─ /api/* (product)        → Railway gateway  (winny_gateway, FastAPI)  → Supabase vgl (RLS)
  └─ /api/* (operator ops)   → Vercel ops proxy (web/api/ops.js, Supabase-gated)
                                   → OVH Hermes dashboard (Caddy gate)
Railway gateway ─ Phase 6 ─ server-side dispatch → OVH Hermes pooled skills
```

- **Gateway** is the product backend: ~30 routers — trading desk (portfolio, orders,
  approvals, backtest, signals, auto_trade, market, broker_connect, webhooks),
  council/rooms/studio, finance, **ops team** (8 departments), connect (6 connectors),
  crm, mail, vault, billing, account, privacy.
- **Auth/tenancy**: every route resolves `_uid(user)` and filters `user_id=uid`;
  Supabase RLS (`auth.uid()=user_id`) is the second wall. Verified by
  `test_ops_tenant_isolation.py`.

## What's solid (don't touch)

- **Security middleware** ([security.py](../winny_gateway/security.py)): body-size cap,
  XFF-spoof-resistant sliding-window rate limiter (bounded memory), full security
  headers (HSTS/nosniff/frame-deny/referrer/permissions), WS limits, error sanitisation.
- **CI** (18 workflows): per-file-isolated pytest across 6 slices, typecheck, lint,
  OSV scan, supply-chain audit, lockfile check. Our `tests/winny_gateway/` suite is
  auto-discovered and gates merges.
- **Ops engine effectiveness contract**: dispatch → guardrails → pre-sync → handler →
  **deterministic acceptance** → budget → handoffs → health. A run that fails its
  invariant is `blocked`, never a silent success. This is the platform's best idea.
- **Owner-gated writes**: connectors `propose → human approve → execute`; the
  autonomous engine can only ever propose.

## Ranked gaps

### Architecture
1. **Frontend is one 2.86 MB chunk (816 KB gzip).** Hurts LCP → hurts SEO and
   first-paint. **Code-split** by route (`React.lazy` on the app shell / heavy desk
   pages) — the public marketing routes should ship a tiny bundle. _High ROI._
2. **SPA SEO** — partially closed (meta/OG/JSON-LD/sitemap shipped). Full win needs
   **prerender of `/` and `/docs`** (react-snap postbuild or `vite-react-ssg`) so
   crawlers/social get real HTML, not a shell. _Medium, own validated change._
3. **Rate limiter is in-memory single-process** (documented). Fine on 1 Railway
   instance; move to Redis sliding-window before horizontal scale.
4. **Phase 6 dispatch is opt-in and unused** — no department graduated yet. First
   candidate: a document-skill (below) on OVH, flipped via `hermes_skill`.

### Business logic
5. **Department artifacts are markdown.** Finance/Legal/CoS should emit **real files**
   (.xlsx / .pdf / .pptx) via ported Anthropic document skills — the single biggest
   "feels like a real company" upgrade. _High._
6. **Outbound copy has no brand gate.** `revenue.draft_followup` / `marketing.draft_campaign`
   propose copy with no tone/guideline check. Add a **brand-QA two-pass** (mirror the
   Legal consensus panel). _Medium-high._
7. **Plan resolution falls back to `DEFAULT_OPS_PLAN=pro`** when no subscription is
   found — generous by default. Confirm that's the intended free-tier behaviour, or
   default to `free` and gate up.

### Analytics / tracking coverage (the funnel is uninstrumented)
The product has no product-analytics events on its core funnel. Minimum set to
instrument (server-side on the gateway, or client via a thin `track()`):

| Stage | Event | Why |
|---|---|---|
| Activation | `provider_connected` (provider) | the connect step is the value moment |
| Activation | `department_seeded` / `selftest_passed` | which departments go live |
| Engagement | `department_run` (slug, job, accepted) | the core loop; success rate per dept |
| Trust | `action_proposed` / `action_approved` / `action_rejected` | approve-rate = trust signal |
| Revenue | `quota_blocked` (plan) / `plan_upgraded` | the upgrade trigger (we already 429 on cap) |

`quota_blocked` → `plan_upgraded` is the conversion event pair; today we 429 but
don't record it, so we can't see the upgrade trigger firing.

### DevOps cycle
8. CI is strong; the missing loop is **deploy verification**. We deploy by `git push`
   (Railway) + `vercel --prod` then poll `/health`. Add a post-deploy **smoke check**
   (health + one authenticated read) as a workflow step or a `make verify` so a bad
   build is caught automatically, not by hand.
9. **Secrets**: exposed keys (Railway token, Stripe sk_live, Supabase service-role)
   remain a launch blocker until rotated — tracked outside the repo.

## Recommended sequence
Document skills (#5) → brand-QA (#6) → code-split (#1) → prerender (#2) → funnel
instrumentation (analytics) → Redis limiter (#3) when scaling. #9 (rotation) is
user-side and blocks commercial launch regardless.
