---
name: systematic-debugging
description: "Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes — find the root cause first; symptom fixes are failure."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Thinking, Debugging, RootCause, Quality]
    related_skills: [verification-before-completion, executing-plans]
---

# Systematic Debugging

Random fixes waste time and create new bugs. **Core principle:** always find the root cause before attempting fixes.

## The Iron Law
```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```
If you haven't completed Phase 1, you cannot propose fixes.

## When to use
ANY technical issue: test failures, production bugs, unexpected behavior, performance, build/integration failures. **Especially** under time pressure, when "one quick fix" seems obvious, or when a previous fix didn't work. Don't skip because it "seems simple" — simple bugs have root causes too, and systematic is *faster* than thrashing.

## The four phases (complete each before the next)

### Phase 1 — Root-cause investigation
1. **Read the error carefully** — full stack trace, line numbers, codes. It often contains the answer.
2. **Reproduce consistently** — exact steps; every time? If not reproducible, gather more data, don't guess.
3. **Check recent changes** — git diff, new deps, config/env differences.
4. **Instrument multi-component systems** — at each component boundary, log what enters/exits and verify env/config propagation. Run once to see *where* it breaks, then investigate that component.
5. **Trace data flow** — where does the bad value originate? Trace backward up the call stack to the source. Fix at the source, not the symptom.

### Phase 2 — Pattern analysis
Find working examples of similar code; read any reference implementation completely; list every difference between working and broken (don't assume "that can't matter"); understand dependencies/config/assumptions.

### Phase 3 — Hypothesis & testing
State a single hypothesis ("X is the root cause because Y"); test with the smallest possible change, one variable at a time; verify before continuing. If it didn't work, form a NEW hypothesis — don't pile fixes on top. If you don't understand something, say so.

### Phase 4 — Implementation
1. Create a failing test case (simplest reproduction) — use `test-driven-development`.
2. Implement a single fix addressing the root cause. No "while I'm here" extras.
3. Verify: test passes, nothing else broke, issue actually resolved (use `verification-before-completion`).
4. If the fix fails and you've tried **3+**, STOP and question the architecture — repeated failures that each surface a new problem elsewhere signal a wrong design, not a failed hypothesis. Discuss with the user before more fixes.

## Red flags — STOP, return to Phase 1
"Quick fix for now"; "just try changing X"; multiple changes at once; "skip the test"; "it's probably X"; proposing solutions before tracing data flow; "one more fix attempt" after 2+ failures.

## When the user signals you're doing it wrong
"Is that not happening?" / "Stop guessing" / "we're stuck?" → STOP, return to Phase 1.

## Bottom line
95% of "no root cause" cases are incomplete investigation. Read the error, reproduce, trace to source, hypothesize, test minimally, fix the source, verify.
