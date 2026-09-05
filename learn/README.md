# LEARN — build roadmap inside `vigil-unified`

**Started 2026-09-05.** An **AZZ&CO product**, not a system built for one client. HBS
FORMATION is **tenant #1 and a licensee** — the first customer, not the owner. That
distinction drives real decisions, so it is written down rather than assumed:

- **Naming.** Nothing in the schema, the package or the product carries `hbs`. The table
  prefix is `learn_`. HBS branding belongs to *a tenant's* white-label settings, never to
  the platform core. (The product still needs a real name — open decision.)
- **IP.** Azz&Co owns the platform outright. The corpus licence being negotiated with HBS
  (`../../hbs-backend/PLAN_OF_ATTACK.md` §5) covers *content*, and must state in writing
  that it transfers nothing of this software — and vice versa.
- **RGPD.** Azz&Co is the **processor**, each tenant is the **controller**. An Article 28
  DPA is a hard gate before the second tenant, including the one with HBS.
- **Design partner is not owner.** HBS's needs shape the first release; they do not get to
  be the only shape. Every feature gets asked "would CFA Rhône Pro want this too?"

Target: feature parity with the LMS market (Digiforma, Dendreo, Moodle, 360Learning) plus
the Qualiopi compliance layer they do not have. The vitrine redirect is the last phase.

Master plan and reasoning: `../../hbs-backend/PLAN_V2.md` (architecture, roles, Qualiopi
coverage) and `../../hbs-backend/PLAN_OF_ATTACK.md` (commercial sequencing).

---

## Where the code lives

```
learn/                  ← this package: the whole LMS/TMS
├─ migrations/              ← SQL, applied in order
├─ roles.py                 ← the 6-role catalogue + capability checks
├─ db.py                    ← tenant-scoped query helpers (wraps winny_gateway.db)
├─ routes/                  ← mounted into winny_gateway.app.create_app()
└─ README.md                ← this file
```

Imported from `winny_gateway`, not rewritten:

| Primitive | Module | Use here |
|---|---|---|
| Supabase JWT via JWKS | `winny_gateway.auth.get_current_user` | who is calling |
| Delegation on behalf of a user | `winny_gateway.auth.effective_user` | the agent ceiling |
| Cross-scope query guard | `winny_gateway.db._scope_ok_*` | re-keyed to `tenant_id` |
| Rate limit, body cap, XFF | `winny_gateway.security.SecurityMiddleware` | as-is |
| **sha256 hash chain + verify** | `winny.common.audit` | **émargement evidence** |
| Private bucket + extraction | `winny_gateway.routes.vault` | the coffre |
| Stripe plans + quotas | `winny_gateway.ops.billing` | tenant subscriptions |
| Approval queue | `winny_gateway.routes.approvals` | agent proposes, human validates |

Nothing under `winny/`, `hermes_*`, `agent/` or the trading routes is modified.

---

## Roadmap — each phase has a checkable goal

## Status — all phases delivered, 2026-09-05

| Phase | State | Evidence |
|---|---|---|
| **P0 Foundation** | ✅ | 6 roles, 81 capabilities, cross-tenant read = 0 rows, cross-tenant write = `cross_tenant_violation` |
| **P1 Planning** | ✅ | 3 days → 6 slots, double-booking = 409 with the range, one query → 7/6/1/6 rows for four callers |
| **P2 Émargement** | ✅ | chain genesis→1→2→3, `permission denied` on update *and* delete, agent refused, `verify → intact` |
| **P3 Qualité** | ✅ | action with no cause refused, réclamation → action in one query, 100 % response rate / 4.50 |
| **P4 Assessment** | ✅ | no `correct` column reachable, 10/20 → `intermediaire`, blocs 100 % / 0 %, `attempt_closed` |
| **P5 Documents & coffre** | ✅ | retention 2029/2031/2032/2036, `retention_active` + `legal_hold` both refuse, certificat = 3.5 h of 21 h |
| **P6 Content** | ✅ | prerequisite locked → unlocked, versioning never mutates, at-risk classification |
| **P7 Reporting** | ✅ | audit manifest: 10 pieces, 4 missing, each naming its indicator |
| **P8 Comms** | ✅ | notifications need a named human approver; agent refused; signalement admin-only (V10 ind. 12) |
| **Importer** | ✅ | dry-run before apply; imported attendance archived, never converted to a signature |
| **Tenant-#2 gate** | ✅ | `DPA signé = false` blocks readiness; sub-processors + registre seeded |
| **P9 Front end** | ✅ | `learn.ts` client, dashboard + calendrier pages, routed, `tsc --noEmit` clean |
| **P10 Vitrine funnel** | ✅ | public catalogue with its population, lead creates a demande not an account |
| **P11 Mobile** | ✅ | offline queue; `signed_at` stays server-side, device time is evidence |

**71 endpoints · 15 migrations · 104 tests (95 pass, 9 skip without a DSN) · 38 tables, all with forced RLS and a policy.**

### The reorder, and why

The build roadmap below was written with the qualité loop at P6. That contradicts
`PLAN_V2.md` §10.6, which — after the Qualiopi gap analysis — put it **second**, on the
grounds that indicator 30 is the single most-failed indicator nationally (~44 %) and the
loop is cheap and independent of everything else. I wrote the roadmap from the LMS feature
list and let that override the compliance analysis. The compliance analysis was right.

So: **qualité moves ahead of content delivery.** Order from here is
qualité → assessment/positionnement → documents → content → reporting.

Two things also missing from the roadmap entirely, both from `GAP_ANALYSIS.md` §4:

- **An importer** (Digiforma / Dendreo / Excel). An OF switching vendors must bring its
  history. Without it every prospect is asked to abandon their records, and that objection
  ends most deals. It is the item most likely to decide whether this sells, and it was
  not a phase.
- **The tenant-#2 gate** — Art. 28 DPA, sub-processor list, registre de traitement,
  reversibility export. Not a feature; a hard gate before a second organisme exists.

### Migration ledger

| | What | Note |
|---|---|---|
| 0000 | reset the abandoned Cassandra scaffold | **not applied** — different Supabase account |
| 0001 | tenancy, 6 roles, capabilities, helpers | |
| 0002 | fix the session-variable prefix | the `hbs_`→`learn_` rename missed `hbs.` |
| 0003 | `learn_app` / `learn_readonly` roles | policies were inert: Supabase connects as a superuser |
| 0004 | programmes, sessions, créneaux, inscriptions | |
| 0005 | émargement, chain, absences, sheet | |
| 0006 | schema-qualify `digest()` | pgcrypto lives in `extensions` on Supabase |
| 0007 | chaining trigger → `SECURITY DEFINER` | app role must not hold crypto access |
| 0008 | append-only revokes from named roles | policies alone made it a silent no-op |
| 0009 | qualité: surveys, réclamations, actions, risks | the action↔cause link is NOT NULL |
| 0010 | assessment: questions, attempts, grading, blocs | answers never leave via the public view |
| 0011 | documents, coffre, rétention, marque blanche | deletion refused by trigger, not by convention |
| 0012 | cours, modules, parcours, progression, xAPI | versioning and prerequisites are structural |
| 0013 | export d'audit, notifications, signalement | the manifest reports absence as loudly as presence |
| 0014 | reprise de données, DPA, registre, réversibilité | imported attendance is never a signature |
| 0015 | évidence d'émargement différé | both times visible, device clock never authoritative |

Four of fifteen are repairs, all found by executing against a real database rather than by
reading. That ratio is the argument for not deferring verification.

### Open

- **Routes have not been driven over HTTP** — needs `LEARN_DATABASE_URL`; host, port,
  database and user are known, the password is not.
- **Nothing is committed.** `learn/` is untracked and `winny_gateway/app.py` is modified.
- **Sharing a database with the live HBS site.** No collisions, site data untouched, but
  the wrong permanent home for a product licensed to several organismes.
- **The product has no name.** `learn` is a package name standing in for one.

---

### P0 · Foundation — tenancy, roles, capabilities
`learn_tenants`, `learn_companies`, `learn_profiles`, the 6-role catalogue with
`can_create_users` / `data_scope` / `is_read_only`, a capability matrix
(role × resource × action), the `learn_tenant_table()` helper that cannot create a table
without a policy, `learn_append_only()`, and the hierarchy trigger.

**Goal:** `select * from learn_roles` returns 6 rows; a query as an admin of tenant A
returns zero rows of tenant B; a CI test fails the build if any `learn_%` table has RLS off
or zero policies. All three shown with real output.

### P1 · Catalog, planning, enrolment *(LMS: catalog & enrolment)*
`learn_programs`, `learn_sessions`, `learn_session_slots` (the demi-journée), `learn_enrollments`,
`learn_resources`. Recurrence expansion to materialised slots, `EXCLUDE` constraint against
formateur and room double-booking, ICS feed per user, `_can` capabilities returned per row.

**Goal:** a 3-day session yields 6 slot rows; double-booking a formateur returns 409 naming
the conflicting slot; the ICS URL opens in a real calendar client.

### P2 · Émargement *(the compliance differentiator)*
Sign in/out per slot for apprenant and formateur, evidence bundle chained with
`winny.common.audit`, absence + justification, counter-signature, feuille PDF/A.

**Goal:** a full signature round-trip produces a PDF/A whose chain passes `verify_chain()`;
an `UPDATE` on the signature table is rejected **by the database**.

### P3 · Content delivery *(LMS: authoring & delivery)*
`learn_courses` / `modules` / `lessons`, media in the vault, SCORM 1.2/2004 via `scorm-again`
where a tenant has packages, xAPI statements to our own table, `learn_lesson_progress`.

**Goal:** a learner opens a module, progress persists across sessions, and an xAPI statement
is written; a SCORM package plays and reports completion.

### P4 · Assessment *(LMS: gradebook & assessment)*
Positioning quiz (indicator 8), quiz engine with question banks, auto-grading, exam sessions
with proctor telemetry, review queue, gradebook per session.

**Goal:** a learner completes a positioning quiz → level assigned → enrolment; the gradebook
shows per-learner scores and exports.

### P5 · Documents & certificates *(LMS: certification)*
Versioned templates → Gotenberg → PDF/A → vault with `retention_until` and `legal_hold`.
Convention / contrat / convocation / attestation / certificat de réalisation. DocuSeal for
signature envelopes. Expiry and recertification.

**Goal:** generating a convention produces a PDF/A in the vault with retention three years
out; a certificate is computed from signed attendance, not typed.

### P6 · Qualité loop *(criterion 7 — the 44 % national failure)*
Appréciations from four stakeholder groups triggered off session end, réclamations register
with resolution tracking, improvement actions linked to the feedback that caused them,
risk register, programme review cycle.

**Goal:** a session ending schedules four surveys; a réclamation can be traced to the
improvement action it produced.

### P7 · Reporting & analytics *(LMS: reporting + indicators 1–3)*
Per-role dashboards, computed indicateurs de résultats with provenance, the Qualiopi audit
export (one ZIP per session), published figures feeding the public site.

**Goal:** the published satisfaction rate traces back to the responses that produced it;
the audit ZIP for a finished session contains all six document types.

### P8 · Communication & compliance automation
Announcements, session channels, notifications, auto-assignment by role, renewal
forecasting, the signalement channel required by V10 indicator 12.

### P9 · Front end
Six role dashboards on the existing React shell (`AuthGate`, sidebar, design tokens,
20-locale i18n already present). WCAG AA — required by indicator 26 and by any public buyer.

### P10 · Vitrine redirect
`hbs-formation.fr` → this app: the enrolment funnel. Public formation page → demande →
positioning quiz → account → enrolment → convocation. Deep links with campaign attribution.

### P11 · Mobile
Capacitor is already wired (`npm run mobile:sync android`). The mobile-specific feature is
QR or geofenced émargement in the room.

---

## Rules that hold across every phase

1. **`tenant_id` on every table, added by `learn_tenant_table()`, never by hand.**
2. **Evidence tables are append-only in the database** — `UPDATE`/`DELETE` revoked, not
   merely unused.
3. **One endpoint per capability, never one per role.** The row set differs, the route does
   not.
4. **The API returns `_can` with each row**; the front end renders controls from that and
   never infers them from the role.
5. **Deletion refuses anything under `legal_hold` or inside `retention_until`.**
6. **The agent never signs, issues, sends or grants** — it proposes into the approval queue.
