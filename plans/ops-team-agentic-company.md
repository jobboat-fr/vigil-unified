# Ops Team — an agentic company

Status: **plan / not started**. Last updated 2026-06-21.

A single page where every company **department is an autonomous agent-team** with a
mandate, KPIs, a work queue, scheduled routines, and the ability to escalate to the
VIGIL council. You supervise agents instead of doing the work.

Decisions locked with the owner (2026-06-21):

| Decision | Choice |
|---|---|
| Autonomy | **Fully autonomous** — departments execute end-to-end on their schedules without a per-task approval gate. (Guardrails below are non-negotiable, not approval gates.) |
| Engine | **Hermes profiles + cron** on OVH, reached through the Supabase-gated ops proxy. Departments = profiles. |
| First step | **This written plan first**, then build. |
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
  autonomy (text: autonomous|gated|advisory), status (active|paused),
  guardrails (jsonb: {daily_task_cap, spend_cap_usd, allowed_tools[],
                      irreversible_requires_owner: true}),
  created_at, updated_at

ops_tasks
  id, user_id, department_id, trigger (cron|webhook|manual|escalation),
  title, input (jsonb), status (queued|working|needs_review|done|blocked|halted),
  hermes_session_id, output_artifact_id, council_run_id,
  cost_usd, error, created_at, updated_at

ops_routines            -- thin mirror of the Hermes cron job owning the schedule
  id, department_id, cron_job_id, schedule, prompt, enabled

ops_events              -- the activity feed (also written to audit_events)
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
POST   /v1/ops/tasks                        dispatch a manual task → Hermes session
POST   /v1/ops/tasks/{id}/escalate          send a task's output to the council
GET    /v1/ops/feed                         merged activity feed (ops_events)

POST   /v1/ops/routines                     create a routine (→ Hermes cron job)
PATCH  /v1/ops/routines/{id}                enable/disable/reschedule

POST   /v1/ops/standup                      Chief of Staff convenes a cross-dept room → artifact
POST   /v1/ops/pause-all                    GLOBAL KILL SWITCH (pauses every cron + blocks dispatch)
GET    /v1/ops/brief                        Chief of Staff daily brief (council-compiled)
```

Dispatch maps to existing ops-proxy endpoints: create routine → `POST /api/cron/jobs`;
manual task → `POST /api/sessions` (or a cron `trigger`); status → `GET /api/sessions/{id}`;
provision department → `POST /api/profiles`. The gateway records the `hermes_*` ids on
the task/routine rows so the board can poll status.

---

## 6. The autonomous work loop + guardrails

Because departments are **fully autonomous**, the loop runs without your click — and
that is exactly why the guardrails are load-bearing:

```
trigger (cron | webhook | manual | council escalation)
   ↓  gateway checks guardrails  (daily_task_cap, spend_cap, tool allowlist, dept not paused)
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

## 7. Frontend — `OpsTeamPage`

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

## 9. Phased delivery

- **P0 — read-only org board.** Render cards from data that already exists: cron jobs
  → routines, recent artifacts → outputs, council status. Pure aggregation, no new
  agent wiring. Ships the page + the `departments` registry. *(Smallest provable slice.)*
- **P1 — dispatch + ledger.** `ops_tasks`, manual dispatch → Hermes session, live
  status polling, activity feed, guardrail scaffolding + kill switch.
- **P2 — autonomous routines + webhooks.** Department cron routines + inbound webhook
  triggers running unattended, with caps + audit fully enforced.
- **P3 — Chief of Staff + council.** Cross-department routing, standups, daily brief,
  council circuit breaker, escalation between departments.

---

## 10. Risks & open questions

- **OVH capacity.** N autonomous profiles on cron multiply load on the single OVH box
  (already saw OOM from runaway Chromium). Need per-box concurrency limits + the spend/
  task caps from day one.
- **Profile sprawl.** Each department is a profile; provisioning/teardown must be clean
  so departments don't leak profiles.
- **Cost.** Fully autonomous = continuous LLM spend. The spend cap + a company-wide
  budget readout on the page are not optional.
- **Secrets.** Department agents acting on Finance/CRM need scoped credentials; reuse
  the existing broker-scoping / `effective_user` model, never the owner token broadly.
- **Roster confirmation.** Launch set proposed in §2 (Finance, Revenue, Support, Eng,
  Chief of Staff) — confirm before P0.

---

## 11. First slice (when approved)

1. `015x_ops_team.sql` — `departments`, `ops_tasks`, `ops_routines`, `ops_events`.
2. `winny_gateway/routes/vigil/ops.py` — `/v1/ops/departments` + `/v1/ops/feed` (P0 read).
3. `web/src/lib/vigil.ts` — `vigil.ops` client.
4. `web/src/pages/OpsTeamPage.tsx` — the board (from the mockup) wired to P0 data.
5. Tests in `tests/winny_gateway/` mirroring the studio/rooms suite (hermetic, fake DB).
