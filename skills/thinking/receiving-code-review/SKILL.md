---
name: receiving-code-review
description: "Use when receiving code-review feedback, before implementing suggestions — especially if feedback seems unclear or technically questionable. Verify before implementing; reasoned pushback over performative agreement."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Thinking, Review, Quality, Discipline]
    related_skills: [requesting-code-review, systematic-debugging]
---

# Receiving Code Review

Code review requires technical evaluation, not emotional performance. **Core principle:** verify before implementing; ask before assuming; technical correctness over social comfort.

## Response pattern
1. **Read** the complete feedback without reacting.
2. **Understand** — restate each requirement in your own words (or ask).
3. **Verify** against the codebase reality.
4. **Evaluate** — is it technically sound for THIS codebase?
5. **Respond** — technical acknowledgment or reasoned pushback.
6. **Implement** — one item at a time, test each.

## Forbidden responses
Never: "You're absolutely right!", "Great point!", "Thanks for catching that!", or any performative agreement / gratitude, and never "let me implement that now" before verification. **Instead:** restate the requirement, ask clarifying questions, push back with reasoning if wrong, or just do the work (actions > words). If you catch yourself about to write "Thanks" — delete it and state the fix.

## Unclear feedback
If any item is unclear, STOP — don't implement anything yet; ask for clarification first. Items may be related; partial understanding → wrong implementation. ("I understand 1,2,3,6. Need clarification on 4 and 5 before proceeding.")

## External vs. user feedback
- **From the user:** trusted — implement after understanding; still ask if scope is unclear; no performative agreement.
- **From external reviewers (incl. automated):** be skeptical, check carefully. Before implementing, check: correct for this codebase? breaks existing behavior? a reason the current impl exists? works on all targets? does the reviewer have full context? If it seems wrong, push back with technical reasoning. If you can't verify, say so and ask for direction. If it conflicts with the user's prior decisions, stop and discuss.

## YAGNI check
If a reviewer suggests "implementing properly," grep for actual usage first. Unused → propose removing it (YAGNI). Used → implement properly.

## Implementation order
Clarify everything unclear first; then blocking issues (breaks/security) → simple fixes → complex fixes; test each individually; verify no regressions.

## When to push back
Suggestion breaks existing behavior, reviewer lacks context, violates YAGNI, technically incorrect for this stack, legacy/compat reasons exist, or it conflicts with the user's architecture. Push back with technical reasoning, not defensiveness; reference working tests/code.

## Acknowledging correct feedback
"Fixed — [what changed]." / "Good catch — [issue]. Fixed in [location]." Just fix it and show it in the code. No gratitude expressions.

## If you pushed back and were wrong
"You were right — I checked [X], it does [Y]. Implementing now." State the correction factually and move on; no long apology.

## GitHub threads
Reply inside the review comment thread, not as a top-level PR comment.

## Bottom line
External feedback = suggestions to evaluate, not orders to follow. Verify. Question. Then implement. No performative agreement; technical rigor always.
