---
name: verification-before-completion
description: "Use when about to claim work is complete, fixed, or passing, before committing or creating PRs — requires running verification commands and confirming output before any success claim. Evidence before assertions, always."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Thinking, Verification, Quality, Discipline]
    related_skills: [writing-plans, executing-plans, systematic-debugging]
---

# Verification Before Completion

## Overview

Claiming work is complete without verification is dishonesty, not efficiency.

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags — STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!")
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

**Tests:** Run the test command, see `34/34 pass`, then say "All tests pass." Never "should pass now."

**Regression tests (TDD red-green):** Write → run (pass) → revert the fix → run (MUST FAIL) → restore → run (pass). Not "I've written a regression test" without the red-green proof.

**Build:** Run the build, see exit 0, then "build passes." A passing linter does not prove compilation.

**Requirements:** Re-read the plan → checklist → verify each → report gaps or completion. Not "tests pass, phase complete."

**Agent delegation:** Agent reports success → check the VCS diff → verify the changes → report the actual state. Don't trust the report.

## When To Apply

**ALWAYS before:** any success/completion claim, any expression of satisfaction, any positive statement about work state, committing, PR creation, task completion, moving to the next task, delegating to agents.

**Applies to:** exact phrases, paraphrases, synonyms, implications of success — ANY communication suggesting completion/correctness.

## The Bottom Line

Run the command. Read the output. THEN claim the result. This is non-negotiable.
