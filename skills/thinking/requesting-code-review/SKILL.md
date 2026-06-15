---
name: requesting-code-review
description: "Use when completing tasks, implementing major features, or before merging — dispatch a reviewer with crafted context to catch issues before they cascade."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Thinking, Review, Quality]
    related_skills: [subagent-driven-development, receiving-code-review, verification-before-completion]
---

# Requesting Code Review

Dispatch a reviewer subagent to catch issues early. Give it precisely crafted context — the work product and requirements — never your session history. **Core principle:** review early, review often.

## When to request
**Mandatory:** after each task in subagent-driven development, after a major feature, before merge to main.
**Valuable:** when stuck (fresh perspective), before refactoring (baseline), after a complex bug fix.

## How
1. **Get the diff range:**
   ```bash
   BASE_SHA=$(git rev-parse HEAD~1)   # or origin/main
   HEAD_SHA=$(git rev-parse HEAD)
   ```
2. **Dispatch a reviewer subagent** with: a brief description of what you built, what it should do (the plan/requirements), and `BASE_SHA..HEAD_SHA`. Ask for: strengths, then issues graded Critical / Important / Minor, then an assessment.
3. **Act on feedback:** fix Critical immediately, Important before proceeding, note Minor for later. Push back (with reasoning) if the reviewer is wrong.

> The platform's `/code-review` (and `/code-review ultra`) is the user-triggered equivalent for the current branch/PR — use it for heavier multi-agent review.

## Red flags — never
Skip review because "it's simple"; ignore Critical issues; proceed with unfixed Important issues; argue with valid technical feedback. If the reviewer is wrong, push back with technical reasoning and show the code/tests that prove it.
