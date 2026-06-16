---
name: crm
description: "Customer relationship management — capture and qualify leads, convert them to deals, advance deal stages, manage contacts/organizations, and log every interaction (calls, emails, notes, tasks). Use for any 'who is this contact / what's the pipeline / move this deal / log this call' request."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [CRM, Sales, Pipeline, Contacts, Communications]
    related_skills: [cold-email, cfo-report, brainstorming]
---

# CRM — pipeline, contacts & communications

The data model and lifecycle below are extracted from the Frappe CRM (open-source) and rebuilt as our own. The backend lands in `winny_gateway/routes/vigil/` + tables per the port plan; this skill is the methodology the agent follows.

## Data model
- **Lead** — an unqualified prospect: name, email, phone/mobile, organization, job_title, **status** (New → Contacted → Qualified → Unqualified/Junk), source, industry, owner, annual_revenue, no_of_employees, `converted` flag, lost_reason/notes, SLA/first-response tracking.
- **Deal** — a qualified opportunity (created by converting a Lead): linked organization + contacts, **status/stage** (Qualification → Demo/Proposal → Negotiation → Won/Lost), **probability %**, next_step, owner, annual_revenue, source, industry, lost_reason.
- **Contact** — a person: name, emails, phones, job_title, linked organization. (A deal has many contacts.)
- **Organization** — a company: name, website, industry, territory, no_of_employees, annual_revenue.
- **Activities** — **Task** (todo with due date/owner), **Call Log** (inbound/outbound, duration, notes), **Note**, **Communication** (email thread, with a communication_status).
- **Reference data** — Lead/Deal Status, Lead Source, Industry, Territory, Lost Reason, SLA (response_by / first_response_time).

## Lifecycle
```
Lead (New → Contacted → Qualified)
   │  qualify + convert  (carry org, contact, source, industry)
   ▼
Deal (Qualification → Demo/Proposal → Negotiation)
   ├─► Won   (record amount, close date)
   └─► Lost  (record lost_reason + notes)
```

## Operations the agent performs
1. **Capture a lead** — dedupe against existing leads/contacts (by email/phone) first; never create a duplicate. Set source + owner.
2. **Qualify** — ask the qualifying questions, set status, capture org + job_title + need.
3. **Convert lead → deal** — carry over org/contact/source/industry; set initial stage + probability; propose a next_step.
4. **Advance a deal** — move stage, update probability, set the next_step; on Won record amount + close date; on Lost require a lost_reason.
5. **Log interactions** — calls, emails (link to the Communication thread), notes, tasks with due dates. Track first-response SLA.
6. **Report pipeline** — open deals by stage, weighted value (Σ amount × probability), aging, win rate, next steps due.

## Constraints
- **NEVER** create a duplicate contact/lead — dedupe by email/phone first.
- **NEVER** send an outbound email/message without human approval (compose → review → send via the **Mail** transport).
- **NEVER** fabricate pipeline figures — every deal value/stage traces to a record.
- **ALWAYS** require a `lost_reason` when marking a deal Lost, and a next_step on every open deal.
- Keep personal/contact data scoped to the owning org (multi-tenant) — never leak across tenants.

## Output
A pipeline/contact view or a recorded change (lead/deal/activity), with the next action surfaced.

> **Routes to →** the **CRM** surface (pipeline + contacts); outbound via **Mail** (+ `cold-email`); deal reviews in the **Council**; pipeline-value math in **Finance/Calculations**; account briefs as **Studio** artifacts.
