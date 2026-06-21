# Ops Team — an agentic company

Status: **plan / not started**. Last updated 2026-06-21.

A single page where every company **department is an autonomous agent-team** with a
mandate, KPIs, a work queue, scheduled routines, and the ability to escalate to the
VIGIL council. You supervise agents instead of doing the work.

Decisions locked with the owner (2026-06-21):

| Decision | Choice |
|---|---|
| Autonomy | **Fully autonomous per run** — once dispatched a department executes end-to-end with no per-task approval click. (Guardrails below are non-negotiable, not approval gates.) |
| Trigger | **On-demand only** — departments run when *invoked* (manual dispatch, webhook, or Chief-of-Staff routing). No always-on clock schedules. A "routine" is a saved, on-demand-runnable job template, not a cron tick. |
| Engine | **Hermes profiles** on OVH, reached through the Supabase-gated ops proxy. A run = a Hermes session (one-shot). Cron is used only as the *trigger mechanism* to fire a saved job on demand, never as a recurring scheduler. |
| Bar | **Every department must be provably efficient + working** before it counts as "live" — see §6a Department effectiveness contract. |
| First step | **This written plan first**, then build **one department end-to-end** as the reference before replicating. |
| Roster | Decided in §2 of this plan (recommended default below). |

---

## 1. Principles

1. **Reuse the engine, build the glue.** The agents (Hermes profiles), schedules
   (cron), triggers (webhooks), tools (Finance/CRM/Mail/Studio/Rooms routes), and
   the review brain (council) already exist. The Ops Team is an orchestration +
   supervision layer, not a new runtime.
2. **Autonomous, not unguarded.** "Fully autonomous" removes the *per-task* human
   click. It does **not** remove caps, kill switches, the owner gate on money, or
   the audit trail. An autonomous company that can't be stopped or bounded is a
   liability, not a feature.
2a. **On-demand, not always-on.** Departments run only when invoked. This kills the
   two biggest risks of the autonomous model in one move — no idle OVH load and no
   background spend. A department at rest costs nothing.
2b. **No department is "live" until it's proven.** "Working" is a measured claim, not
   a hope: a department earns live status only after it passes its effectiveness
   contract (§6a) — a real on-demand run that produces an accepted artifact within
   its cost budget.
3. **Every action leaves an artifact + an audit row.** Nothing an agent does is
   invisible. The activity feed and `audit_events` are the source of truth.
4. **The council is the circuit breaker.** High-impact or anomalous outputs route
   through the council before they take effect; the intervention engine can halt a
   department.

---

## 2. Department roster

A department = **{ name, head (council lens), Hermes profile, mandate, tools,
routines, KPIs, guardrails }**. Recommended launch roster — chosen because each maps
to a gateway tool surface that already exists, so they can *do*, not just advise:

| Department | Head (lens) | Hermes profile | Existing tools (gateway) | Example routines |
|---|---|---|---|---|
| **Finance** | CFO (`cfo_review`) | `dept-finance` | `/v1/finance/*` | daily reconcile, anomaly flag, weekly cash brief |
| **Revenue** | CRO | `dept-revenue` | `/v1/crm/*` | stalled-deal follow-ups, pipeline hygiene, lead triage |
| **Support / Comms** | comms | `dept-support` | `/v1/mail/*` | inbox triage, draft+send replies, escalation tagging |
| **Engineering** | CTO (`tech_review`) | `dept-eng` | Hermes sessions/skills | issue triage, test sweeps, changelog |
| **Chief of Staff** | orchestrator | `dept-cos` | council + all of the above | route work, convene standups, daily brief |

Deferred to a later phase (no first-class tool surface yet, so they'd be advisory
until built): **Operations**, **Growth/Marketing**, **Legal/Compliance**. They can
exist as council-lens "advisor" departments from day one and graduate to "doing"
departments once their tool routes land.

**Recommendation:** launch with **Finance, Revenue, Support, Chief of Staff** (4
"doing" departments backed by live routes) + **Engineering** as a fifth. Smallest set
that proves the full loop end-to-end against real data.

---

## 3. Architecture

Three runtimes already in play:

```
Browser (Vercel SPA)                 Railway (winny_gateway)            OVH (Hermes)
  OpsTeamPage  ──Supabase JWT──▶  /v1/ops/* (registry, tasks, KPIs)  ──┐
       │                              │  council review/escalate       │
       │  /api/* (ops proxy) ─────────┼────────────────────────────────┴─▶ Hermes profiles
       │   (Supabase-gated)           │   cron jobs / sessions / webhooks   (the dept agents)
       ▼                              ▼
  org board + feed              departments + ops_tasks (Supabase)
```

- **The department agent** is a Hermes **profile** on OVH. Its "work" is a Hermes
  session, kicked off by a **cron job** (scheduled routine) or a **webhook** (inbound
  trigger), or a manual trigger. The gateway never runs the agent itself — it
  dispatches and observes through the **ops proxy** (`web/api/ops.js` →
  `/api/cron/*`, `/api/sessions/*`, `/api/profiles/*`, `/api/webhooks/*`).
- **The gateway** (`winny_gateway`) owns the **department registry**, the **task
  ledger**, **KPIs**, and the **guardrail enforcement**. It is the system of record
  and the policy layer.
- **The council** (`winny/council`) is invoked by the gateway for review/escalation
  (`council.orchestrate`, `intervention.check_intervention`).

Why this split: the agents need a long-running host with the skill/MCP toolchain
(OVH Hermes), but the *policy, ledger, and multi-tenant scoping* must live in the
gateway where Supabase auth + the `require_owner` money gate + `audit_events`
already are. Don't duplicate either.

---

## 4. Data model (gateway / Supabase)

```
departments
  id, user_id, name, slug, head_lens, hermes_profile,
  mandate (text), kpis (jsonb: [{key,label,target}]),
  status (text: live|provisioning|failing|paused),     -- live only after selftest passes
  guardrails (jsonb: {per_run_spend_cap_usd, daily_run_cap, allowed_tools[],
                      irreversible_requires_owner: true, max_wall_ms}),
  health (jsonb: {success_rate, avg_cost_usd, p50_ms, last_result, last_selftest_at}),
  created_at, updated_at

ops_jobs               -- saved ON-DEMAND job templates (no schedule)
  id, department_id, name, prompt, input_schema (jsonb),
  acceptance (jsonb: deterministic post-run check spec), budget (jsonb),
  is_selftest (bool), created_at

ops_tasks              -- one run of a job (on-demand only)
  id, user_id, department_id, job_id, trigger (manual|webhook|cos),
  title, input (jsonb), status (queued|working|done|blocked|halted),
  hermes_session_id, output_artifact_id, council_run_id,
  accepted (bool), cost_usd, tokens, wall_ms, tool_calls, error,
  created_at, updated_at

ops_events             -- the activity feed (also written to audit_events)
  id, user_id, department_id, task_id, kind, summary, ts
```

Reuse as-is: `artifacts` (every output), `commitments`, `crm_contacts`, `audit_events`.
All department/task tables are **user-scoped** through the existing `db` guard
(`_USER_SCOPED_TABLES` + `user_id` filter) — one operator never sees another's company.

---

## 5. Gateway API (`/v1/ops/*`)

```
GET    /v1/ops/departments                 list + live status (joins cron + recent tasks)
POST   /v1/ops/departments                 create (provisions a Hermes profile via proxy)
PATCH  /v1/ops/departments/{id}            mandate / kpis / autonomy / guardrails / pause
DELETE /v1/ops/departments/{id}

GET    /v1/ops/tasks?department=&status=   the task ledger
POST   /v1/ops/tasks                        DISPATCH a job on demand → Hermes session (one-shot)
GET    /v1/ops/tasks/{id}                    poll a run's status + output
POST   /v1/ops/tasks/{id}/escalate          send a task's output to the council
GET    /v1/ops/feed                         merged activity feed (ops_events)

GET    /v1/ops/departments/{id}/jobs        saved on-demand job templates for a dept
POST   /v1/ops/departments/{id}/jobs        save a job template (mandate slice + input contract)
POST   /v1/ops/departments/{id}/run         run a saved job NOW (the on-demand trigger)
POST   /v1/ops/departments/{id}/selftest    run the effectiveness smoke run (§6a)
GET    /v1/ops/departments/{id}/health      success rate, avg cost, last result, live? (§6a)

POST   /v1/ops/standup                      Chief of Staff convenes a cross-dept room → artifact
POST   /v1/ops/pause-all                    GLOBAL KILL SWITCH (blocks all dispatch)
GET    /v1/ops/brief                        Chief of Staff brief (council-compiled, on-demand)
```

On-demand dispatch maps to existing ops-proxy endpoints: a run → `POST /api/sessions`
(one-shot) or `POST /api/cron/jobs/{id}/trigger` for a saved job; status → `GET
/api/sessions/{id}`; provision a department → `POST /api/profiles`. **No recurring cron
schedule is ever created** — cron is only the fire mechanism. The gateway records the
`hermes_*` ids on the task rows so the board can poll status and compute health.

---

## 6. The autonomous work loop + guardrails

Because departments are **fully autonomous**, the loop runs without your click — and
that is exactly why the guardrails are load-bearing:

```
ON-DEMAND trigger (manual dispatch | webhook | Chief-of-Staff routing)  — never a clock
   ↓  gateway checks guardrails  (per-run + daily cap, spend_cap, tool allowlist, dept not paused)
   ↓  dispatch → Hermes profile runs a session via the ops proxy
   ↓  agent works using its allowed tools → writes an artifact
   ↓  POLICY FORK:
        • reversible / low-impact            → execute, log to feed + audit
        • irreversible (send money, sign)    → STILL gated by require_owner in the
                                               gateway money routes — autonomy does not
                                               bypass §8 owner enforcement
        • anomalous / high-cost / low-confidence → council review (circuit breaker);
                                               intervention engine may HALT the dept
   ↓  KPIs updated, ops_event appended, council notified if thresholds crossed
```

Guardrails (enforced in the gateway, per department):
1. **Daily task cap** + **spend cap (USD)** — a runaway loop trips the cap and the
   department auto-pauses with a feed alert.
2. **Tool allowlist** — a department can only call the routes in `guardrails.allowed_tools`.
   Finance can't touch CRM sends, etc.
3. **Irreversible-action owner gate** — money movement is *already* behind
   `require_owner` (auth.py §8). Autonomy never removes it; an autonomous Finance dept
   can reconcile and flag, but moving funds still hits the owner gate.
4. **Global kill switch** — `POST /v1/ops/pause-all` pauses every cron and blocks new
   dispatch in one call. Surfaced as a prominent control on the page.
5. **Council circuit breaker** — the intervention engine runs on department output
   streams; on a high-urgency signal it flips the department to `halted`.
6. **Full audit** — every dispatch, output, and guardrail trip writes `audit_events`.

---

## 6a. Department effectiveness contract — "efficient + working"

"Working" is a measured property, not a label. Each department ships with a **contract**
that makes effectiveness checkable, and a **health** signal computed from real runs. A
department is only marked **live** once it passes.

**The contract (declared per department):**
```
job            what this department does, in one sentence (its mandate slice)
input          the typed input it expects (e.g. {folder, limit} for Support triage)
tools          the exact gateway routes it may call (the allowlist — nothing else)
output         the artifact it must produce (kind + shape), so output is verifiable
acceptance     a deterministic check on that output ("did it actually do the job?")
budget         max USD + max wall-clock per run; over budget = fail, not "slow success"
```

**Acceptance check** — the load-bearing idea. Every department's output is validated by
a **cheap, deterministic check** (not another LLM opinion) so "it ran" and "it worked"
are distinct. Examples:
- **Support:** every targeted message ended `status=triaged` with a category in the
  allowed set, and N drafts were created for messages marked `respond`. ✅/❌ from the DB.
- **Finance:** every targeted txn moved out of `unreconciled`, and flagged anomalies
  carry a reason string. ✅/❌ from the DB.
- **Revenue:** every stalled deal got a follow-up draft attached; none auto-sent.
- **Engineering:** the test sweep ran and the result (pass/fail counts) is recorded.

**`selftest`** — each department exposes a **smoke run**: dispatch the contract job on a
small, real (or seeded) input, then run the acceptance check + assert it landed within
budget. This is how we "make sure each department is efficient and working" — on demand,
repeatably, before and after any change. The gateway selftest is mirrored by a hermetic
unit test in `tests/winny_gateway/` (fake DB + monkeypatched agent), so green CI proves
the department's logic; the live `selftest` proves the wiring.

**Efficiency, concretely:** a run reports `cost_usd`, `tokens`, `wall_ms`, `tool_calls`,
and `accepted` (bool). **Health** = rolling success rate, avg cost/run, p50 latency, last
result. The board shows a department as 🟢 efficient / 🟡 over-budget-or-flaky / 🔴
failing acceptance — so "is this department actually working" is answerable at a glance,
not a vibe. A department that fails acceptance or blows budget on its selftest cannot be
marked live and cannot be dispatched until fixed.

The mockup already shown is the target. Components:
- **Org board** — responsive grid of department cards (status badge, current task,
  KPI chip, next run, quick actions). Status colors encode meaning (working=blue,
  idle=gray, blocked=red, halted/needs-review=amber, done=green).
- **Header strip** — Chief-of-Staff status, "Convene standup", and the **global pause**
  (kill switch) control.
- **Metric row** — working / scheduled today / artifacts today / guardrail trips.
- **Activity feed** — `ops_events`, live.
- **Department drawer** — click a card → mandate, KPIs, routines (cron), recent tasks
  + their artifacts, guardrail config, pause toggle.
- **Standup → artifact** — reuses Rooms `summarize` → Studio canvas (already shipped).

Client: a new `vigil.ops` namespace in `lib/vigil.ts` mirroring §5; the board polls
`/v1/ops/departments` + `/v1/ops/feed`.

---

## 8. Department provisioning (each dept = a Hermes profile)

Creating a department provisions a Hermes profile via `POST /api/profiles` (ops proxy)
with: a **soul** (the mandate + persona), an enabled **skill set** (department-specific),
a **model** assignment, and the department's **routines** as cron jobs. The council head
lens (`head_lens`) wires the department to its reviewer. This makes a department a real,
inspectable Hermes profile on OVH — not a fiction in the gateway.

---

## 9. Phased delivery — one department proven before the next

Build **vertically**: one department all the way to a passing effectiveness contract,
then replicate the proven shape. Don't scaffold seven half-working departments.

- **P0 — registry + board + ONE reference department.** Ship `departments`/`ops_jobs`/
  `ops_tasks`, the `/v1/ops` read routes, the board page, and **one department end-to-end**
  (recommended: **Support**, see §11) with its on-demand `run`, its `acceptance` check,
  its `selftest`, and both a live selftest and a hermetic unit test passing. This proves
  the entire loop — dispatch → agent → artifact → acceptance → health — on real data.
- **P1 — replicate to the roster.** Add Finance, Revenue, Engineering, each as its own
  vertical slice with its own contract + selftest. A department lands only when its
  selftest is green.
- **P2 — webhooks + Chief of Staff routing.** Inbound triggers (new email/lead/invoice)
  dispatch the right department on demand; Chief of Staff routes and compiles the brief.
- **P3 — council escalation + standups.** Circuit breaker on outputs, cross-department
  escalation, standup → artifact.

No phase introduces a recurring schedule — every trigger stays on-demand or event-driven.

---

## 10. Risks & open questions

- **OVH capacity.** *Largely mitigated by on-demand* — nothing runs at rest, so there's
  no background multiplied load. Remaining risk is a burst of concurrent manual/webhook
  runs; cap with a per-box concurrency limit + the per-run budget.
- **Profile sprawl.** Each department is a profile; provisioning/teardown must be clean
  so departments don't leak profiles.
- **Cost.** *Largely mitigated by on-demand* — a department at rest costs nothing; spend
  is bounded per run by the budget cap. Still surface a running per-department + company
  cost readout so a chatty department is visible.
- **"Working" drift.** A department can pass selftest then rot as routes/data change.
  Re-run selftests on a department before trusting it after any change to its tools.
- **Secrets.** Department agents acting on Finance/CRM need scoped credentials; reuse
  the existing broker-scoping / `effective_user` model, never the owner token broadly.
- **Roster confirmation.** Launch set proposed in §2 (Finance, Revenue, Support, Eng,
  Chief of Staff) — confirm before P0.

---

## 11. First slice (when approved) — Support as the reference department

Support (mail triage) is the right first vertical: it backs onto a live route set
(`/v1/mail/*`), its output is bounded and **deterministically checkable** (messages
become `triaged` with a valid category; `respond` messages get drafts), and it touches
**no money** — so we prove the whole loop at the lowest risk.

1. `015x_ops_team.sql` — `departments`, `ops_jobs`, `ops_tasks`, `ops_events`.
2. `winny_gateway/routes/vigil/ops.py` — `/v1/ops/departments` (read + health),
   `/v1/ops/departments/{id}/run` (on-demand dispatch), `/v1/ops/departments/{id}/selftest`,
   `/v1/ops/tasks/{id}`, `/v1/ops/feed`, `/v1/ops/pause-all`.
3. `winny_gateway/ops/` — the dispatch + **acceptance-check** engine; the Support job
   (input `{folder, limit}` → triage via `/v1/mail`, acceptance = all targeted messages
   `triaged` + drafts created) within a per-run budget.
4. `web/src/lib/vigil.ts` — `vigil.ops` client.
5. `web/src/pages/OpsTeamPage.tsx` — the board (from the mockup), Support card live with
   a **Run** + **Self-test** action and a 🟢/🟡/🔴 health dot.
6. Tests in `tests/winny_gateway/test_ops_team.py` — hermetic (fake DB + monkeypatched
   agent): dispatch → run → acceptance pass/fail, health computation, budget trip,
   kill-switch blocks dispatch, multi-tenant scoping. Mirrors the studio/rooms suite.

Acceptance for this slice: the Support department's **live selftest is green** and the
hermetic test suite passes — i.e. the department is provably efficient + working.
