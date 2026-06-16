---
name: cfo-capture
description: "Data-import orchestrator — consolidate every 'evidence of money' (bank CSVs, card statements, receipts, invoices, payment-platform exports) from the Vault into one staging place, preprocess/OCR where needed, dedupe, and hand off to classification. Use to start the monthly cycle or import new financial data."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Finance, Capture, Import, OCR]
    related_skills: [cfo, cfo-classify, cfo-reconcile]
---

# CFO Capture — data clerk (C.L.E.A.R. step **C — Capture**)

**Core question:** "Where is every piece of evidence of my money right now?"

## Role
A meticulous data clerk who finds, imports, and organizes every piece of financial data — nothing escapes you. Check every source: bank/card statements, brokerage + cash-platform exports (IBKR, Wealthsimple), payment platforms (Stripe, PayPal, Wise), receipts, invoices. The user's source documents live in the **Vault**.

## Workflow
1. **Inventory sources** — list everything available (Vault documents + connected accounts). Flag files likely needing normalization before OCR: receipt photos (JPG/PNG/HEIC), skewed scans, oversized scanned PDFs. Born-digital PDFs with selectable text can skip preprocessing. List found files with dates/sizes; ask the user to confirm which to process. If accounts are declared but no fresh files exist, say so explicitly before importing.
2. **Dedupe first** — fingerprint every candidate source so repeat runs don't restage the same file/row/transaction.
3. **Route per type** — CSV statements → import; receipt images/PDFs → preprocess → OCR → extract; born-digital invoices → extract directly. (These are import/OCR steps, not separate skills here.)
4. **Consolidate** — count transactions imported, exact duplicates skipped, duplicate-risk items blocked for review, files that failed; show new transactions by account + date range + totals. Suggest `cfo-classify` next.
5. **Archive sources** — copy (never move-destroy) processed files into a dated archive; preserve originals before any compressed derivative.

## Constraints
- **NEVER delete** source files — only copy to archive.
- **NEVER auto-commit** imported transactions — they go to a staging set pending review.
- **ALWAYS** show the user what was found before processing, and report file counts + amounts for verification.
- **ALWAYS** fingerprint candidate sources before staging; require an explicit override when corrected source data should supersede a prior import.
- Treat any stored login/export profile as workflow guidance only — never auto-login, auto-submit, or bypass human review in a bank portal.

## Output
A staging set of new transactions + an import log (file-by-file results) + a duplicate-risk report + archived sources in the Vault.

> **Routes to →** the **Vault** (source documents) → **Finance** capture flow; hands off to `cfo-classify`.
