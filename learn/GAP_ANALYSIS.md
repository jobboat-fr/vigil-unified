# LEARN — what exists, what was discussed, what a product needs

**2026-09-05.** Three columns compared: the 3D walkthrough
(`claude.ai/code/artifact/a84d90bb…`), everything settled in conversation and written into
`../../hbs-backend/PLAN_V2.md`, and what a training platform sold to multiple organismes
must have regardless of whether anyone asked.

Legend — **A** in the artifact · **P** in the plan · **B** built (code exists)

> **Revised 2026-09-05 after P0–P2 shipped.** The §1 table below is now accurate: the rows
> marked "⏳ helper ready" for émargement and the evidence chain are **built and verified
> against the live database**. The §3 and §4 gaps are unchanged — nothing in P0–P2 touched
> the LMS half or the product half, which is exactly what the ratio in §5 predicted.

---

## 1. Covered, and coherent across all three

| Capability | A | P | B |
|---|:-:|:-:|:-:|
| 6-role model with scope + capability axes | ✅ | ✅ | ✅ 0001 |
| Tenant isolation, restrictive floors, CI guard | ✅ | ✅ | ✅ 0001 + test |
| One endpoint per capability, row set differs by role | ✅ | ✅ | ✅ `_can` in roles.py |
| Émargement in/out, both sides, append-only | ✅ | ✅ | ✅ 0005+0008 |
| Hash-chained evidence + verification | ✅ | ✅ | ✅ own trigger — `winny.common.audit`'s design, in Postgres |
| Coffre with retention clock and legal hold | ✅ | ✅ | ⏳ helper ready |
| Agent delegation with read/write ceilings | ✅ | ✅ | ✅ roles.py |
| Agent may never sign, issue or grant | ✅ | ✅ | ✅ `learn_no_agent_writes()` |
| Planning: sessions, créneaux, conflicts | ✅ | ✅ | ✅ 0004 |
| Site vitrine → funnel → inscription | ✅ | ⚠️ thin | ⏳ P10 |
| Positioning quiz (indicator 8) | ✅ | ✅ | ⏳ P4 |

The artifact is **ahead of the plan** in one place: the acquisition funnel. It was drawn
in detail — public page, form, tunnel, quiz, account, enrolment, convocation — before
`PLAN_V2.md` had more than a sentence about it. Treat the artifact as the spec for P10.

---

## 2. Discussed, decided, but absent from the artifact

| Gap | Why it matters | Phase |
|---|---|---|
| **Criterion 7 loop** — appréciations from 4 stakeholder groups, réclamations register, improvement actions linked to their cause | **The #1 national non-conformité (~44 %).** The `Qualité` object is drawn but no journey touches it | P6 |
| **`entreprise` role has no tile** | Delta Logistique pays for 8 seats and has no seat itself; sixth role in the model, invisible in the demo | P1 |
| **Facturation → OPCO → paiement** | Money stops at the convention. No devis, no facture, no prise en charge, no relance. The OPCO is not an actor and it is the one that pays and audits | P5 |
| **Nothing is ever sent** | Convocations are permanently "en brouillon". The approval-then-send path — the thing that makes the agent safe — is described but never walked | P8 |
| **Certification / RNCP** | HBS is certifiante (RNCP37275, RNCP38575). No jury, no blocs de compétences, no taux d'obtention — that is indicator 3, and it applies | P4/P7 |
| Handicap: référent, adaptation, réseau (ind. 26) | One line on the vitrine page, nothing behind it | P6 |
| Formateur competency files (ind. 21-22) | A formateur is a login with no CV, diploma or CPD record | P6 |
| Sous-traitance register (ind. 27, widened in V10) | HBS uses external formateurs; contractual traceability required | P6 |
| Veille légale/métiers/innovations (23-25), risk analysis (32) | Mechanical, dated, sourced entries. Boring and frequently failed | P6 |
| Signalement violence/harcèlement/discrimination (ind. 12, new in V10) | Required from 1 November 2026 | P8 |
| RGPD export/erasure honouring legal hold | `privacy.py` deletes unconditionally today — porting it unchanged hands a learner a button that destroys a tenant's evidence | P0/P5 |

---

## 3. Neither drawn nor discussed — but every LMS on the market has it

This is the "same LMS the market offers" bar, and most of it has never come up.

| Missing | Notes |
|---|---|
| **Course authoring** | We planned to *deliver* content and never to *build* it. Digiforma and 360Learning both ship an authoring UI. Without it a tenant needs a second tool |
| **Learning paths / curricula / prerequisites** | "Complete A before B", multi-course programmes. Structural, not cosmetic — retrofitting ordering into a flat course table is painful |
| **Gradebook** | Per-learner, per-session scores in one grid, exportable. Assumed but never modelled |
| **Certificates with expiry + recertification** | Compliance LMS staple: a certificate valid 24 months, auto-reassignment before it lapses. Sells itself to any OF doing habilitations |
| **Notification engine** | Reminders, digests, escalations, per-user preferences. Currently notifications are implied everywhere and owned by nothing |
| **Bulk import of learners (CSV)** | The Delta Logistique scenario has Marie pasting 8 names. At 200 that is a blocker |
| **Waitlists and capacity management** | 12 places, 15 requests. Universal |
| **Recurring mandatory assignment** | Auto-assign by role/tenure/location. This is what corporate LMS buyers pay for |
| **Competency / skills framework** | Maps directly onto RNCP blocs de compétences — a genuine differentiator on the French market, not a generic feature |
| **Discussion / cohort social** | Weakest-value item here; note it and move on |
| **Content versioning** | A programme revised mid-cohort must not change what past learners were assessed on |
| **Multi-language content** | UI has 20 locales; *content* has none |
| **Custom reports + scheduled delivery** | Every buyer asks. Fixed dashboards are not enough |
| **Offline mobile** | Capacitor is wired; offline sync is not. Matters for émargement in a room with no signal |

---

## 4. Neither drawn nor discussed — and required because this is a **product**

New as of the Azz&Co framing. A tool needs none of this; a licensed product cannot ship
without it.

| Missing | Why |
|---|---|
| **Import from Digiforma / Dendreo / Excel** | **The single biggest one.** An OF switching vendors must bring its history — learners, sessions, past émargements, documents. Without an importer every prospect is asked to abandon their records, and that objection ends most deals. Nobody has mentioned it once |
| **Product name and brand** | It cannot be called HBS anything. Currently unnamed |
| **White-label per tenant** | Logo, colours and legal mentions on convocations, attestations and the learner portal. An OF will not send its learners a document branded by someone else. Near-free if designed into the template engine at P5; expensive after |
| **Self-serve trial + demo tenant** | Sales needs a sandbox with realistic data, not a screenshare of HBS's real learners |
| **Plan gating + seat metering** | Billing exists; nothing enforces plan limits |
| **VAT handling for exempt buyers** | OFs are VAT-exempt on formation and **cannot reclaim input VAT** — every euro of subscription costs them €1.20. Pricing must be quoted TTC on this market or it reads 20 % dearer than it is |
| **Automated tenant provisioning** | Today a tenant is a manual insert |
| **Reversibility export** | A departing customer leaves with evidence intact, because their 3-to-10-year retention obligation outlives the subscription. Build it early and it answers the lock-in objection; build it late and it is an emergency |
| **Art. 28 DPA, sub-processor list, registre, breach runbook** | Absence of a compliant DPA is a standalone CNIL violation. Hard gate before tenant #2 |
| **Status page, incident comms, SLA** | Their audit evidence lives here; silence during an outage loses the renewal |
| **Public API + webhooks** | Bigger OFs integrate with their CRM or HRIS |
| **SSO / SAML** | Any OF above ~50 staff will ask |
| **Pentest report + security page** | Procurement asks before signature, not after |
| **Accessibility statement (WCAG)** | Indicator 26 and public-funded buyers both require it |
| **Help centre + in-app onboarding** | Every hour of hand-holding is margin |
| **Fleet analytics for Azz&Co** | Which tenants are healthy, which are churning. Invisible today |

---

## 5. Honest read

The **compliance spine is the strongest part** — isolation, evidence, the agent's limits
are designed further than most products ever bother, and the hash chain already exists.

The **LMS half is the thinnest**, which is awkward given the goal is market parity:
authoring, learning paths, gradebook and recertification are all absent from both the
drawing and the plan.

And the **product half barely exists** — it was written as an internal tool until today.
Of everything above, **the importer is the item most likely to decide whether this sells**,
and it has never been discussed.
