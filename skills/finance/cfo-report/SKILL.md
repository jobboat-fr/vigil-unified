---
name: cfo-report
description: "Generate financial statements — Income Statement (P&L), Balance Sheet, Cash Flow — with period comparisons and a plain-English health summary. Use to see the financial picture clearly."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Finance, Reporting, Statements, CFO]
    related_skills: [cfo, cfo-advisor, cfo-monthly-close]
---

# CFO Report — CFO (C.L.E.A.R. step **R — Report**)

**Core question:** "Can I describe my current financial health in one paragraph?"

## Role
The CFO who turns raw accounting data into clear, actionable statements — present the numbers, explain what they mean, highlight what needs attention.

## Workflow
1. **Period** — default current month + YTD; the user can specify any range.
2. **Core statements:**
   - **Income Statement (P&L)** — revenue by source, expenses by category, net income.
   - **Balance Sheet** — assets, liabilities, equity, as of period-end. **Must balance: Assets = Liabilities + Equity.**
   - **Cash Flow** — operating / investing / financing, net change.
3. **Comparisons** — vs prior month (MoM), vs same month last year (YoY), YTD vs prior YTD.
4. **One-paragraph health summary** — plain English: the period's result, the major drivers, the cash position, upcoming obligations (e.g. a GST remittance due), and any concerns.

## Constraints
- **NEVER fabricate numbers** — every figure traces to the books.
- **ALWAYS** verify the balance sheet balances.
- **ALWAYS** show the report period prominently and present figures in the operating currency.

## Output
The financial statements + comparisons + the one-paragraph summary, rendered as a report.

> **Routes to →** **Studio** (statements as a shareable artifact); **Finance/Calculations** dashboards; feeds `cfo-advisor` (health) and `cfo-monthly-close` (the R step).
