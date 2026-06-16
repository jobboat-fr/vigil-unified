---
name: cfo-monthly-close
description: "Month-end close — run the full cycle (capture → classify → reconcile → report → validate) for one month and produce a close packet. Use at month-end to close the books."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Finance, Close, Controls, Reporting]
    related_skills: [cfo-capture, cfo-classify, cfo-reconcile, cfo-report]
---

# CFO Monthly Close — controller (C.L.E.A.R. step **A — Automate**)

## Role
The controller running the monthly close. Orchestrate every step, ensure nothing is missed, produce a close packet.

## Pre-flight
- [ ] All bank + card statements for the month are in the Vault
- [ ] Receipts captured
- [ ] No unresolved flagged transactions from prior months

## Workflow
1. **Capture (C)** — `cfo-capture` for the month: import statements + receipts. Report transactions imported.
2. **Log (L)** — `cfo-classify` new transactions: auto-classify high-confidence (with approval), review medium/low, apply tax treatment. Report classified vs needs-review.
3. **Extract (E)** — `cfo-reconcile` each account: compare to statements, resolve discrepancies, add balance assertions. Report accounts reconciled.
4. **Report (R)** — `cfo-report` for the month: income statement (month + YTD), balance sheet (month-end), cash-flow summary, prior-month comparison.
5. **Close** — validate everything passes, then generate a close packet and snapshot it (a tagged, immutable record of the close).

## Close packet
A short Markdown record: Summary (revenue / expenses / net income / cash position), Reconciliation (accounts reconciled, assertions added), Open Items (anything unresolved), Approved-by + date.

## Constraints
- **NEVER** close a month with unreconciled accounts — warn, don't force.
- **NEVER** skip validation.
- **ALWAYS** produce a close packet for the audit trail and snapshot/tag the close.
- If any step fails, **stop and report** — don't proceed with a broken close.

## Output
A close packet + the period's statements + a tagged close snapshot.

> **Routes to →** the **Finance** close flow; the close packet renders as a **Studio** artifact; statements from the **Vault**.
