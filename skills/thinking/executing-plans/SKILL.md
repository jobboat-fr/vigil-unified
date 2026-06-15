---
name: executing-plans
description: "Use when you have a written implementation plan to execute, with review checkpoints. Loads the plan, reviews it critically, runs each task with its verifications, stops on blockers."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Thinking, Implementation, Execution, TDD]
    related_skills: [writing-plans, subagent-driven-development, verification-before-completion]
---

# Executing Plans

## Overview

Load the plan, review it critically, execute all tasks with their verifications, report when complete.

**Announce at start:** "I'm using the executing-plans skill to implement this plan."

**Note:** This agent does higher-quality work when it can dispatch subagents. If subagent support is available, prefer the `subagent-driven-development` skill (fresh subagent per task + review) over inline execution.

## The Process

### Step 1 — Load and review the plan
1. Read the plan file.
2. Review critically — identify any questions or concerns about the plan.
3. If concerns: raise them with the user before starting.
4. If none: create a task list and proceed.

### Step 2 — Execute tasks
For each task:
1. Mark it in_progress.
2. Follow each step exactly (the plan has bite-sized steps).
3. Run the verifications as specified.
4. Mark it completed.

### Step 3 — Complete
After all tasks are done **and verified**:
- Invoke the `verification-before-completion` skill — run the full test/build commands fresh and confirm output before any "done" claim.
- Then summarize what shipped and commit (on a branch, not main/master, without explicit consent).

## When to Stop and Ask

**STOP immediately when:** you hit a blocker (missing dependency, failing test, unclear instruction), the plan has critical gaps, you don't understand an instruction, or a verification fails repeatedly. **Ask rather than guess.**

## When to Revisit
Return to Step 1 when the user updates the plan based on your feedback, or the fundamental approach needs rethinking. Don't force through blockers.

## Remember
- Review the plan critically first.
- Follow steps exactly; don't skip verifications.
- Invoke referenced skills when the plan says to.
- Stop when blocked, don't guess.
- Never start implementation on `main`/`master` without explicit user consent — work on a branch/worktree.

## Integration
- **writing-plans** — creates the plan this skill executes.
- **subagent-driven-development** — preferred when subagents are available.
- **verification-before-completion** — the completion gate before any success claim.
