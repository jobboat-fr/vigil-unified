---
name: mail-triage
description: "Inbox triage — fetch mail, classify it (spam/ham, category, priority), auto-tag it, and surface what needs action. Learns from the user's corrections. Use for 'sort my inbox', 'what needs a reply', 'is this spam', or routing receipts/invoices and client mail."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Mail, Triage, Inbox, Classification]
    related_skills: [himalaya, cold-email, crm, cfo-capture]
---

# Mail Triage

Triage intelligence extracted from **Mailpile** (Bayesian spam classification + auto-tagging + filters) run over the **himalaya** transport (IMAP/SMTP) the runtime already provides. himalaya moves mail; this skill decides what each message *is* and what to do with it.

## Role
A sharp inbox manager: nothing important gets buried, nothing junk wastes attention. Classify every message, tag it, prioritize it, and surface the short list that actually needs the user.

## Workflow
1. **Fetch** — pull new/unread mail via `himalaya` (don't re-process already-triaged messages).
2. **Classify each message** on three axes:
   - **Spam vs ham** — Bayesian (spambayes-style: per-token spam probability combined via chi-squared), trained on the user's own filing. Score, don't hard-delete.
   - **Category** — Client/Deal, Receipt/Invoice, Newsletter, Notification/Automated, Personal, Recruiting, Other (learned from sender + subject + content patterns).
   - **Priority** — needs-reply (a question/request addressed to the user, with a deadline?) vs FYI vs ignore.
3. **Auto-tag + propose actions** (review before applying, like classification's confidence gates):
   - Client/Deal mail → propose logging to the **CRM** contact/deal + draft a reply.
   - Receipt/Invoice → propose adding the attachment to the **Vault** + handing to `cfo-capture`.
   - Newsletter/Notification → tag + archive.
   - Likely spam → tag (quarantine), never silently delete.
   - Needs-reply → flag with a suggested response + a task.
4. **Learn from corrections** — when the user re-files/re-tags, update the classifier + filter rules so the same sender/pattern is handled next time. Generalize sender/subject patterns; don't hardcode private content.
5. **Summarize** — "N triaged: X need a reply (listed), Y receipts → Vault, Z newsletters archived, W quarantined."

## Constraints
- **NEVER** auto-delete mail — spam is quarantined/tagged for review.
- **NEVER** auto-send a reply — compose → review → send via `himalaya` only on approval.
- **NEVER** move money or act on a payment request in an email without explicit human confirmation (phishing surface).
- **ALWAYS** show the triage proposal before applying tags/actions in bulk; keep mailbox data scoped to the owning user.

## Output
A triaged inbox: tags applied, the short "needs you" list with suggested replies, and items routed to CRM / Vault / tasks.

> **Routes to →** **Mail** surface (over `himalaya`); client mail → **CRM**; receipts/invoices → **Vault** + `cfo-capture`; reply drafts → review-then-send; action items → tasks.
