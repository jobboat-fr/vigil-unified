---
name: subagent-driven-development
description: "Use when executing an implementation plan with independent tasks in the current session — dispatch a fresh subagent per task with two-stage review (spec compliance, then code quality)."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Thinking, Implementation, Subagents, Review]
    related_skills: [writing-plans, executing-plans, requesting-code-review, verification-before-completion]
---

# Subagent-Driven Development

Execute a plan by dispatching a fresh subagent per task, with a two-stage review after each: spec compliance first, then code quality.

**Why subagents:** delegate each task to a focused agent with isolated context — they never inherit your session history; you construct exactly the context they need. This preserves your own context for coordination.

**Core principle:** fresh subagent per task + two-stage review (spec → quality) = high quality, fast iteration.

**Continuous execution:** don't pause to check in between tasks. Execute all tasks. The only reasons to stop: an unresolvable BLOCKED status, genuine ambiguity, or all tasks complete.

## When to use
- You have an implementation plan, tasks are mostly independent, and you're staying in this session → **this skill**.
- Parallel/separate session → `executing-plans`. Tightly-coupled tasks → manual or brainstorm first.

## Per-task loop
1. **Dispatch an implementer subagent** with the full task text + scene-setting context (don't make it read the plan file — hand it the text).
2. If it asks questions, answer before it proceeds.
3. It implements (TDD), tests, commits, self-reviews.
4. **Spec-compliance review** (separate subagent): does the code match the spec — nothing missing, nothing extra? Loop until ✅.
5. **Code-quality review** (separate subagent): only after spec is ✅. Loop until approved.
6. Mark the task complete; next task.
7. After all tasks: a final whole-implementation review, then the `verification-before-completion` gate before any "done" claim.

## Model selection
Use the least powerful model that fits each role: mechanical 1-2 file tasks → fast/cheap; multi-file integration → standard; architecture/design/review → most capable.

## Handling implementer status
- **DONE** → spec review. **DONE_WITH_CONCERNS** → read concerns; address correctness/scope ones before review. **NEEDS_CONTEXT** → provide it, re-dispatch. **BLOCKED** → diagnose: more context (re-dispatch same model), more reasoning (stronger model), too large (split), or plan is wrong (escalate to the user). Never force the same model to retry unchanged.

## Red flags — never
- Start implementation on `main`/`master` without explicit user consent.
- Skip either review, or proceed with unfixed issues.
- Run code-quality review before spec compliance is ✅ (wrong order).
- Dispatch multiple implementer subagents in parallel (conflicts).
- Make a subagent read the plan file instead of giving it the text.
- Let self-review replace actual review.

## Integration
- `writing-plans` creates the plan. `requesting-code-review` supplies the reviewer framing. Subagents follow TDD per task. `verification-before-completion` is the final gate. Use `executing-plans` instead for a parallel/separate session.
