# VIGIL × WinnyWoo — Unified Build Log

A living journal of the mining/adaptation work. **Every step:** what was done + where it's heading. Newest entries at the bottom of each section.

## Sources (cloned to `~/vigil-refs/`, reference only — we mine, we don't run their runtimes)
| Repo | Mine for | Lands in |
|---|---|---|
| `obra/superpowers` | brainstorm/think/plan/verify methodology + session-start hook | `skills/thinking/` + a Hermes hook / persona rule |
| `MikeChongCan/cfo-stack` | finance/fiscal skills (Beancount-based) | `skills/finance/` |
| `coreyhaines31/marketingskills` | marketing skills | `skills/marketing/` |
| `frappe/crm` | CRM data model + lifecycle flows (Frappe app — extract, don't run) | `skills/crm/` + data model + tool |
| `mailpile/Mailpile` | triage intelligence (spambayes/tagging) over the himalaya transport | `skills/mail/` |

## Method per skill (one at a time)
1. **Read** the source skill.
2. **Adapt** → fork frontmatter (`name`, `description`, `version`, `author: VIGIL × WinnyWoo`, `license: MIT`, `metadata.hermes.tags`/`related_skills`); strip foreign-runtime assumptions (Claude-Code plugin paths, Beancount-CLI-only, slash-command-only); keep the hard-gates / enforced behaviors; repath defaults (`docs/superpowers/specs/` → `docs/specs/`). Curate, don't dump.
3. **Route** — ask *where in the product is this useful?* and record the target functionalities it should plug into (Meeting Room, Studio/Artifacts, Vault, Council, Trade Desk, Signals, Calculations, Chat, global persona). Two flavors: **global** (bake into SOUL/persona as an always-on behavior) vs **feature** (a specific flow invokes it).
4. **Log** the step (what changed + Routes-to + next).
> Wiring the routes into the actual flows happens as each product flow is built; the routing decision is recorded now so nothing is an orphan skill.

## Routing targets (product functionalities skills plug into)
Meeting Room · Studio/Artifacts · Vault · Council · Trade Desk · Signals/Analysis · Calculations/Models · Chat · global persona (SOUL.md/AGENTS.md).

## Adaptation rules (applied to every mined skill)
1. Frontmatter → fork format. 2. Strip tool-specific assumptions. 3. Keep hard-gates. 4. Repath defaults. 5. Curate, don't dump.

## Progress

### 2026-06-15 — Setup
- Cloned all 5 reference repos to `~/vigil-refs/` (superpowers, cfo-stack, marketingskills, crm, Mailpile). Read structure + representative skills; confirmed the 3 skills repos use agentskills.io frontmatter (drop-in compatible with the fork's loader).
- Created domain folders under `skills/`: `thinking/`, `finance/`, `marketing/`, `crm/`, `mail/`.
- **Heading:** start with the `thinking` domain (superpowers) — your lead ask ("forcefully brainstorm + think on each functionality"), highest leverage because it shapes how every later feature gets built.

### thinking/ (from superpowers) — curated set
Target skills (13 in source; curating to the ones that fit a product-building agent):
`brainstorming`, `writing-plans`, `executing-plans`, `verification-before-completion`, `systematic-debugging`, `subagent-driven-development`, `requesting-code-review`, `receiving-code-review`. (Skipping `using-git-worktrees`, `finishing-a-development-branch`, `using-superpowers`, `writing-skills`, `dispatching-parallel-agents` for now — git/meta-specific; revisit later.)

- [x] **brainstorming** — adapted → `skills/thinking/brainstorming/`. Kept the `<HARD-GATE>` (no implementation before an approved design) + one-question-at-a-time checklist + process flow. Repathed specs; trimmed the Claude-only visual-companion link. **Core of "force the agent to think first."**
  - **Routes to →** **Studio/Artifacts** (brainstorm the artifact's shape before drafting — when assisting in a meeting or solo), **Meeting Room** (when the agent proposes building something mid-session, spec it first), **Calculations/Models** (brainstorm a financial/trading model before computing), **Trade Desk** (brainstorm a new strategy before writing its algorithm), and any "build me X" in **Chat**. Wiring: Studio "create/refine artifact" flow invokes it first; persona rule that creative requests trigger it.
- [x] **writing-plans** — adapted → `skills/thinking/writing-plans/`. Kept bite-sized TDD task structure, no-placeholders rule, self-review, execution handoff. Repathed to `docs/plans/`; dropped `superpowers:` prefixes; removed worktree note.
  - **Routes to →** any **multi-step build**: a new WinnyWoo **strategy/algorithm**, a new **skill/tool**, a Council **action-item → project**, a Studio **multi-section artifact**. Wiring: brainstorming hands off to it; persona rule that non-trivial builds get a plan before code.
- [x] **verification-before-completion** — adapted → `skills/thinking/verification-before-completion/`. Near-verbatim (pure discipline: "no completion claims without fresh verification evidence"). Condensed prose + frontmatter.
  - **Routes to →** **GLOBAL** (bake into SOUL.md/AGENTS.md as an always-on gate): every "done/fixed/passing" claim — **trade-execution** confirmations, **artifact** completion, **strategy/code** changes, **audit** assertions, **meeting summaries**. Not a single feature; a universal pre-claim gate.
- [x] **executing-plans** — adapted → `skills/thinking/executing-plans/`. Kept critical-review-first, stop-on-blocker, branch-not-main rule. Replaced `superpowers:finishing-a-development-branch` (git-meta, not curated) with our `verification-before-completion` as the completion gate; generalized worktree + the "use Claude Code/Codex for subagents" note.
  - **Routes to →** the **implementation phase of any build** (after writing-plans): new strategies, skills, tools, artifacts, features. Global agent build-discipline; pairs with subagent-driven-development.
- [x] **subagent-driven-development** — adapted → `skills/thinking/`. Kept per-task loop + two-stage review (spec→quality) + model selection + status handling + red flags. Repointed `superpowers:` refs to our bare skill names; replaced `finishing-a-development-branch` with `verification-before-completion`; inlined the prompt-template guidance (the `./*-prompt.md` files weren't curated).
  - **Routes to →** implementation phase of multi-task builds (new strategies, skills, features in the unified project). Global dev flow; preferred over executing-plans when subagents are available.
- [x] **systematic-debugging** — adapted → `skills/thinking/`. Kept the Iron Law + four phases + 3-fixes→question-architecture rule + red flags. Tool-agnostic; "human partner" → "the user"; dropped missing supporting-file links (folded the technique inline).
  - **Routes to →** **GLOBAL** — any bug/failure anywhere: Trade Desk data, signal-runner errors, agent tool failures, build failures. Always invoked before proposing a fix.
- [x] **requesting-code-review** — adapted → `skills/thinking/`. Kept when/how/act-on-feedback; generalized the missing template to "dispatch a reviewer with crafted context"; cross-linked our `/code-review` (+ ultra).
  - **Routes to →** before merging any feature/strategy/skill; pairs with the platform `/code-review`.
- [x] **receiving-code-review** — adapted → `skills/thinking/`. Kept verify-before-implement, no-performative-agreement, YAGNI, pushback rules. "human partner" → "the user".
  - **Routes to →** **GLOBAL** — whenever the agent receives review feedback (from the user or `/code-review`).

#### ✅ thinking/ COMPLETE — 8 of 8 curated done.
**Global-persona wiring pending:** `verification-before-completion`, `systematic-debugging`, `receiving-code-review`, and brainstorm-first need to be baked into vigil-unified's SOUL.md/AGENTS.md as always-on behaviors (do this when we assemble the unified persona).
### finance/ (from cfo-stack) — curating ~8 of 30
Adapt off Beancount-CLI / plain-text-accounting + `/cfo-*` slash routing → keep the C.L.E.A.R. methodology + roles + constraints, ground in our **Vault**, route to Finance/Calculations/Studio/Trade-Desk.

- [x] **cfo** (router) → `skills/finance/cfo/`. Finance front-door: minimum-questions routing across the curated set; strip references to non-curated sub-skills; ground in Vault; keep "never guess entity/jurisdiction" + "tax model ≠ compliance approval" constraints.
  - **Routes to →** Finance entry point in Chat; Vault grounding; reports → Studio; reads Trade Desk positions.
- [x] **cfo-advisor** → `skills/finance/cfo-advisor/`. Net worth / savings rate / FIRE / scenario modeling, data-driven, "information not advice" disclaimer kept. Pull figures from books + Vault + Trade Desk positions.
  - **Routes to →** Finance/Calculations dashboard; Studio artifact; Vault + Trade Desk grounding.
- [x] **cfo-capture** (C) → data clerk: inventory sources from the **Vault**, flag OCR-needed docs, dedupe, stage (never auto-commit), consolidate, archive. Generalized Beancount staging paths + the bank-import/receipt-scan/dedupe sub-skill chain into inline steps. **Routes to →** Vault → Finance capture; hands off to cfo-classify.
- [x] **cfo-classify** (L) → staff accountant: rules → pattern → history → inference; confidence gates (HIGH/MED/LOW, never auto-apply); CA/US tax treatment + pass-through guardrail; learn-from-corrections (anonymized). **Routes to →** Finance classify; Vault-grounded; feeds reconcile/tax/report.
- [x] **cfo-reconcile** (E) → controller: statement-vs-books deltas, investigate (missing/dup/timing/fees/FX), balance assertions, PASS/FAIL report. Kept "never fabricate to force a balance / never mark reconciled if delta≠0 / human approval." **Routes to →** Finance reconcile; Vault statements; precedes close.
- [x] **cfo-monthly-close** (A) → orchestrates capture→classify→reconcile→report→validate + close packet; snapshot/tag the close. Generalized git commit/tag. **Routes to →** Finance close; close packet → Studio artifact.
- [x] **cfo-tax-plan** (E) → tax strategist: verify jurisdiction source first (never fabricate rates), assess position, CA/US opportunities, scenarios with cited rates, deadlines, action items. Kept the CRITICAL "not tax advice" disclaimer. **Routes to →** Finance tax; Vault jurisdiction docs; report → Studio.
- [x] **cfo-report** (R) → CFO: P&L + balance sheet (must balance) + cash flow + comparisons + one-paragraph health summary. Generalized Beancount/BQL + file paths. **Routes to →** Studio artifact; Finance/Calculations dashboards.

#### ✅ finance/ COMPLETE — 8 of 8 curated (cfo, cfo-advisor, cfo-capture, cfo-classify, cfo-reconcile, cfo-monthly-close, cfo-tax-plan, cfo-report).
> Note: the finance skills assume a books/ledger store + (eventually) `winny/finance/` per UNIFIED_PORT_PLAN Stage 5. The skills are the methodology layer; the data backend is wired when that stage lands.
### marketing/ (from coreyhaines31/marketingskills) — curated 8 of 40
These are agentskills.io-format + mostly tool-agnostic, so adaptation = **keep the methodology bodies verbatim**, swap to our frontmatter (name/desc/version/author/license/hermes.tags/related), and append a routing note. The shared `.agents/product-marketing.md` context convention is kept (works in any repo).

- [x] **product-marketing** (foundation context every other marketing skill reads first) → Studio positioning artifact; Council marketing lens.
- [x] **copywriting** → Studio copy artifacts; landing pages; Mail email copy.
- [x] **cro** → Studio + Calculations (experiment math); landing-page optimization.
- [x] **seo-audit** → Studio audit report; site/page analysis.
- [x] **analytics** → Calculations/dashboards; Studio report.
- [x] **cold-email** → **Mail** + **CRM** (contacts/sequences); Studio templates.
- [x] **launch** → Studio launch plan; Council launch review; Meeting Room.
- [x] **pricing** → Studio; **Finance** (pricing→revenue); Council pricing review.

#### ✅ marketing/ COMPLETE — 8 of 8 curated.
### crm/ (extracted from frappe/crm — app, not a skills repo)
- [x] **crm** → `skills/crm/crm/`. **Extracted the data model + lifecycle**, rebuilt as our own skill (not a Frappe copy): Lead → qualify/convert → Deal → Won/Lost, with Contact/Organization/Task/Call-Log/Note/Communication + statuses/sources/SLA. Encodes the agent operations (capture+dedupe, qualify, convert, advance, log, report pipeline) + constraints (no duplicate contacts, no auto-send, lost_reason required, tenant-scoped). Backend (tables + `winny_gateway/routes/vigil/`) lands in the port plan; this is the methodology layer.
  - **Routes to →** CRM surface; **Mail** (+ cold-email) for outbound; **Council** deal reviews; **Finance/Calculations** pipeline value; **Studio** account briefs.

### mail/ (extracted from Mailpile — app, not a skills repo)
- [x] **mail-triage** → `skills/mail/mail-triage/`. Put Mailpile's **triage intelligence** (Bayesian spambayes/chi2 spam scoring + auto-tagging + filters) over the existing **`email/himalaya`** transport. Fetch → classify (spam/ham, category, priority) → propose tags/actions (review-gated) → learn from corrections → summarize. Constraints: never auto-delete (quarantine), never auto-send, never act on payment requests without confirmation.
  - **Routes to →** Mail over himalaya; client mail → **CRM**; receipts/invoices → **Vault** + cfo-capture; reply drafts → review-then-send; tasks.

---

## ✅ SKILL MINING COMPLETE — 26 skills across 5 domains
| Domain | Source | Skills |
|---|---|---|
| thinking/ | obra/superpowers | 8 (brainstorm/plan/execute/subagent/debug/verify/review×2) |
| finance/ | MikeChongCan/cfo-stack | 8 (cfo router + advisor + capture/classify/reconcile/close/tax/report) |
| marketing/ | coreyhaines31/marketingskills | 8 (product-marketing + copy/cro/seo/analytics/cold-email/launch/pricing) |
| crm/ | frappe/crm | 1 (model + lifecycle, extracted) |
| mail/ | mailpile/Mailpile | 1 (triage intelligence over himalaya) |

**Open follow-ups (recorded, not blocking):**
1. ~~Global-persona wiring~~ ✅ **DONE** — `docker/SOUL.md` rewritten as the unified VIGIL × WinnyWoo persona with the four always-on principles baked in: **think-first (brainstorming HARD-GATE)**, **evidence-before-claims (verification)**, **root-cause-before-fixes (debugging)**, **technical-rigor-on-feedback (review reception)** — plus the domain capabilities, voice, and hard rules (approval gate, vault grounding, tenant scoping).
2. **Backends** — finance books store + CRM tables/routes land in `winny/finance/` + `winny_gateway/routes/vigil/` (port plan Stage 5).
3. **Feature wiring** — invoke each skill from its routed product flow as those flows are built (Studio→brainstorming, Mail→mail-triage, CRM→crm, Finance→cfo-*, etc.).

### 2026-06-16 — First feature wiring: Studio → brainstorming → artifact (end-to-end proof)
The `brainstorming` thinking skill is now wired to a real product surface as the proof that the agentic spine drives features, not just the persona.
- **Backend** `winny_gateway/routes/vigil/studio.py` (registered in `app.py`) — two-stage flow enforcing the HARD-GATE:
  1. `POST /v1/artifacts/brainstorm` → think-first: returns understanding + clarifying questions + 2-3 approaches with trade-offs + a recommended design. **No artifact produced.**
  2. `POST /v1/artifacts` → drafts only against an approved approach. Plus `GET` (list/get), `DELETE`, `POST /{id}/refine` (Studio side-chat).
  - LLM via the council provider `ask(worker_registry()["primary"], …)` — degrades to a deterministic stub when no API key, so the surface never crashes keyless. Storage in-memory, **scoped to the authenticated user** (same model as rooms).
- **Frontend** `web/src/pages/StudioPage.tsx` (real, replaced scaffold) + `web/src/lib/vigil.ts` `studio.*` client + `Artifact`/`BrainstormPlan` types — composer → "Think it through" → approach cards (Recommended badge) → "Approve & draft" → artifact view + refine. Kind selector (proposal/brief/contract/memo/report), optional Vault grounding box.
- **Verified:** `tsc -b` exit 0; backend imports + route signatures checked; functional smoke (brainstorm→create→list→refine) passes on the stub provider; **tenant scoping enforced** (other user → 404).

### 2026-06-16 — Stage 5 persistence: Studio + Meeting Room onto Supabase
Moved both surfaces off in-memory stores onto the **existing** VIGIL tables (not parallel ones — same lesson as the support_tickets collision): `public.artifacts` (13 live rows) and `public.rooms` (7 live rows), both RLS-on.
- **Migration** `winny_gateway/migrations/010_studio_rooms_persistence.sql` — purely **additive**: `artifacts` += `brief`, `approach`, `stub`; `rooms` += `members jsonb`, `default_lens text`. Applied to project `pqikzrcykdynxhtnjgeh` via Supabase MCP; existing rows untouched.
- **studio.py** now uses `db_insert/db_select/db_update/db_delete` against `artifacts` (content -> `text_dump`, `version` counts revisions, refine bumps `updated_at`). **rooms.py** -> `rooms` (lens -> `default_lens`, members/transcript as jsonb).
- **Scoping:** added `artifacts` + `rooms` to `db._USER_SCOPED_TABLES`, so the admin-client cross-tenant guard now blocks any unscoped read/write — every query carries `user_id = sub`.
- **Verified:** both routers import + routes intact; the exact insert/update/delete column shape round-tripped against the live tables via MCP (no NOT NULL/type/FK issues), with cleanup. Reads/writes now survive restarts (was the in-memory gap).

### 2026-06-16 — Finance backend (the cfo-* skills' ledger)
The books/ledger store the finance skills route into is now real.
- **Migration** `011_finance_ledger.sql` (applied via MCP): `finance_accounts` (chart of accounts) + `finance_transactions` (the ledger: txn_date, signed amount, currency, category, account_id FK, status uncategorized→categorized→reconciled, source, metadata). RLS-on (auth.uid()=user_id + service-role bypass), per-user indexes, updated_at trigger.
- **Routes** `winny_gateway/routes/vigil/finance.py` (`/v1/finance/*`, registered in app.py): accounts list/create; transactions list (status/category filters) / capture / patch (classify+reconcile) / delete; `GET /summary` → P&L rollup (income/expense/net, by_category, reconcile progress). All scoped via `db._USER_SCOPED_TABLES` (+= finance_accounts, finance_transactions).
- **Client** `web/src/lib/vigil.ts` `finance.*` + FinanceAccount/FinanceTxn/FinanceSummary types.
- **Verified:** router imports + routes intact; `tsc -b` exit 0; live capture→classify→reconcile round-trip via MCP (FK to account + updated_at trigger) with cleanup.

### 2026-06-16 — CRM backend (contacts + deal pipeline)
The contacts + pipeline store the `crm` skill routes into (sales_leads is only inbound-lead intake, so this is distinct).
- **Migration** `012_crm.sql` (applied via MCP): `crm_contacts` (name/email/phone/company/title/tags[]/notes/metadata) + `crm_deals` (title, contact_id FK ON DELETE SET NULL, stage lead→qualified→proposal→negotiation→won/lost, value, currency, probability, expected_close). RLS-on, indexes, updated_at triggers.
- **Routes** `winny_gateway/routes/vigil/crm.py` (`/v1/crm/*`, registered): contacts list/create/patch/delete; deals list(filter by stage)/create/patch(move stage)/delete; `GET /pipeline` → per-stage count/value/weighted (value×probability) + open & weighted-open value. Scoped via `db._USER_SCOPED_TABLES` (+= crm_contacts, crm_deals).
- **Client** `web/src/lib/vigil.ts` `crm.*` + CrmContact/CrmDeal/CrmPipeline types + DEAL_STAGES.
- **Verified:** crm router + full `winny_gateway.app` import; `tsc -b` exit 0; live contact→deal→stage-move→FK-set-null round-trip via MCP with cleanup.

**Backends status:** Studio + Meeting Room persisted; Finance + CRM data layers live. Remaining: Mail (himalaya transport + triage) data layer, and frontend pages for Finance/CRM (backends are ready for wiring).

### 2026-06-16 — Mail backend (himalaya transport + triage store) — 4th/4 domain backend
The inbox-triage store the mail-triage skill routes into, fed by the himalaya transport when configured.
- **Migration** `013_mail.sql` (applied via MCP): `mail_messages` (external_id, from/to, subject/snippet/body, received_at, category urgent|respond|fyi|newsletter|spam|archive, priority, triage_score, status, tags[], triaged; UNIQUE(user_id, external_id) so re-sync upserts, NULLs distinct so manual never collide) + `mail_drafts` (review-then-send: status draft|approved|sent). RLS-on, indexes, triggers.
- **Transport** `winny_gateway/mail_bridge.py` — shells out to `himalaya envelope list -o json` when the binary is present (`WINNY_HIMALAYA_BIN`/`_ACCOUNT`), maps envelopes to the ingest shape, and **degrades** to `{available:false}` otherwise (read-only; never sends).
- **Routes** `winny_gateway/routes/vigil/mail.py` (`/v1/mail/*`): messages list(filter)/ingest/patch/delete; `POST /sync` (himalaya→upsert); `POST /messages/{id}/triage` (LLM classify→category+priority+action, stub-degrades); `GET /triage/summary`; drafts CRUD with **send blocked here** (approve only; sending is a separate gated action — persona hard rule). Scoped via `db._USER_SCOPED_TABLES`.
- **Client** `web/src/lib/vigil.ts` `mail.*` + MailMessage/MailDraft/MailTriageSummary types + MAIL_CATEGORIES.
- **Verified:** mail router + full app import; himalaya bridge degrades (available=false, no crash); `tsc -b` exit 0; live round-trip via MCP (manual ingest + idempotent external_id upsert + NULL-distinct + triage patch + draft approve) with cleanup.

**✅ All four skill-domain backends live:** Finance · CRM · Mail data layers + Studio/Meeting-Room persistence. Remaining: Finance/CRM/Mail **frontend pages** (backends ready to wire).
