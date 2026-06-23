# Plugins & skills harvest — what's useful for the agentic company

_Survey of the MCP plugins, skills, and agent types available in the build
environment, mapped to our eight departments. Rule we hold to (per the project's
standing decision): **we mimic the engineering, we don't create a vendor/runtime
dependency on someone else's repo.** Every connector below is built on **our own
connector kit** (`integrations/connector.py`) with the tenant's own token — the
plugins are a *reference for what to build and how the API behaves*, not a runtime
the gateway calls._

## How the catalog maps to us

The available plugins are organised by the *same departments we already have* —
which validates the model and gives a ready-made connector roadmap. We ship 4
connectors today (GitHub, HubSpot, Stripe, Gmail); the table is the backlog.

| Department | We have | High-value adds (plugin seen) | Auth fit for our kit |
|---|---|---|---|
| **Support** | Gmail (IMAP) | **Intercom**, Zendesk-like, Guru (KB) | Intercom = access token ✓ |
| **Finance** | Stripe, Plaid | **QuickBooks**, Square, PayPal, BigQuery | QB/Square/PayPal = OAuth ✗ (need callback infra); token-only first |
| **Revenue** | HubSpot (CRM) | **Close**, Outreach, Apollo, Clay | Close/Apollo = API key ✓; Outreach = OAuth ✗ |
| **Growth (Lead Scout)** | mail-derived | **Apollo**, **ZoomInfo**, Clay (enrichment) | Apollo/ZoomInfo = API key ✓ |
| **Marketing** | — | **Klaviyo** (email), Ahrefs/Similarweb (SEO/competitive), Supermetrics | Klaviyo/Ahrefs = API key ✓ |
| **Legal** | Vault (own docs) | **DocuSign** (signature), Box/Egnyte (doc stores), Atlassian | DocuSign/Box = OAuth ✗; Atlassian token ✓ |
| **Operations** | `commitments` table | **Notion**, **Linear**, Asana, ClickUp, Monday | Notion/Linear = token ✓ |
| **Chief of Staff** | departments | Google Calendar/Drive, Fireflies/Granola (meeting notes) | OAuth ✗ mostly |

### Ranked connector roadmap (value ÷ effort, token-based first)

These fit our kit cleanly (single token, no OAuth callback infra — the same reason
Gmail uses an IMAP App Password):

1. **Notion → Operations** — pull pages/tasks into `commitments`; Operations today
   only reads its own table, so this gives it real input. Integration token.
2. **Intercom → Support** — the actual support inbox alongside email. Access token.
3. **Apollo / ZoomInfo → Lead Scout** — replace the heuristic enrichment in
   `growth.enrich` with real firmographics. API key.
4. **Linear → Operations / Engineering** — issues as commitments. API key.
5. **Klaviyo → Marketing** — turn `marketing.run` campaign artifacts into real
   audiences/flows. Private API key.

OAuth-gated (QuickBooks, Square, PayPal, DocuSign, Outreach, Box) are higher value
but need a callback/refresh-token service we deliberately don't have yet — batch
them behind one small OAuth broker when we commit to it, rather than one-off.

## Skills / agents worth mimicking (not depending on)

- **brand-voice** agent set (`content-generation`, `conversation-analysis`,
  `quality-assurance`, `discover-brand`): a clean blueprint for how **Marketing**
  and **Revenue** should generate *brand-aligned* copy and then **validate it
  against guidelines** before it's proposed. Our `revenue.draft_followup` /
  `marketing.draft_campaign` produce copy with no brand gate — adding a
  "guidelines → generate → QA" two-pass (mirroring this agent split) is the same
  rigor we just gave Legal with the consensus panel. **Mimic the two-pass pattern.**
- **conversation-analysis** (transcripts → voice/messaging patterns): maps to a
  future **Revenue/Support** "learn from won/lost calls" loop (Gong/Fireflies/
  Granola are the sources). Pattern, not dependency.
- **nimble-researcher / nimble-analyst** split (fast gather vs. judgement synth):
  validates our council split (cheap workers gather, chairman/consensus decides).

## The Phase 6 bridge

Phase 6 (just shipped) lets a department job declare `hermes_skill` and route to a
pooled Hermes skill with local fallback. **That is exactly where these connectors
and skill-patterns graduate to**: instead of growing the gateway with N more
connector modules, the heavier ones (OAuth brokers, enrichment, brand-QA) become
**pooled Hermes skills** the departments dispatch to — built once on OVH, shared by
every tenant, billed through the same plan/quota we wired in Phase 7.

## Recommended next action

Build **Notion → Operations** first (token-based, fills the biggest data gap, ~90
lines on the existing kit, same shape as `hubspot.py`), then the brand-QA two-pass
for Marketing/Revenue. Hold the OAuth connectors for a single shared broker.
