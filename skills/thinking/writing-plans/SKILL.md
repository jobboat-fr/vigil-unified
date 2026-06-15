---
name: writing-plans
description: "Use when you have a spec or requirements for a multi-step task, before touching code. Turns an approved design into a bite-sized, test-first implementation plan."
version: 1.0.0
author: VIGIL × WinnyWoo
license: MIT
metadata:
  hermes:
    tags: [Thinking, Planning, TDD, Implementation]
    related_skills: [brainstorming, executing-plans, subagent-driven-development, verification-before-completion]
---

# Writing Plans

## Overview

Write comprehensive implementation plans assuming the engineer has zero context for our codebase and questionable taste. Document everything: which files to touch per task, the code, the tests, docs to check, how to test it. Give the whole plan as bite-sized tasks. DRY. YAGNI. TDD. Frequent commits.

Assume a skilled developer who knows almost nothing about our toolset or problem domain, and doesn't know good test design well.

**Announce at start:** "I'm using the writing-plans skill to create the implementation plan."

**Save plans to:** `docs/plans/YYYY-MM-DD-<feature-name>.md` (user preferences override this default).

## Scope Check

If the spec covers multiple independent subsystems, it should have been broken into sub-project specs during brainstorming. If it wasn't, suggest splitting into separate plans — one per subsystem. Each plan should produce working, testable software on its own.

## File Structure

Before defining tasks, map out which files will be created or modified and what each is responsible for. This is where decomposition decisions get locked in.

- Design units with clear boundaries and well-defined interfaces. One clear responsibility per file.
- You reason best about code you can hold in context at once; edits are more reliable when files are focused. Prefer smaller, focused files.
- Files that change together live together. Split by responsibility, not technical layer.
- In existing codebases, follow established patterns. Don't unilaterally restructure — but if a file you're modifying has grown unwieldy, a split in the plan is reasonable.

## Bite-Sized Task Granularity

**Each step is one action (2-5 minutes):** write the failing test → run it to confirm it fails → implement the minimal code → run tests to confirm they pass → commit.

## Plan Document Header

Every plan MUST start with:

```markdown
# [Feature Name] Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]
**Architecture:** [2-3 sentences about approach]
**Tech Stack:** [Key technologies/libraries]

---
```

## Task Structure

````markdown
### Task N: [Component Name]

**Files:**
- Create: `exact/path/to/file.py`
- Modify: `exact/path/to/existing.py:123-145`
- Test: `tests/exact/path/to/test.py`

- [ ] **Step 1: Write the failing test**
```python
def test_specific_behavior():
    result = function(input)
    assert result == expected
```
- [ ] **Step 2: Run test to verify it fails** — `pytest tests/path/test.py::test_name -v` → FAIL ("function not defined")
- [ ] **Step 3: Write minimal implementation**
```python
def function(input):
    return expected
```
- [ ] **Step 4: Run test to verify it passes** — same command → PASS
- [ ] **Step 5: Commit**
```bash
git add tests/path/test.py src/path/file.py
git commit -m "feat: add specific feature"
```
````

## No Placeholders

Every step must contain the actual content an engineer needs. These are **plan failures** — never write them:
- "TBD", "TODO", "implement later", "fill in details"
- "Add appropriate error handling / validation / handle edge cases"
- "Write tests for the above" (without actual test code)
- "Similar to Task N" (repeat the code — tasks may be read out of order)
- Steps that say what to do without showing how (code blocks required for code steps)
- References to types/functions/methods not defined in any task

## Remember
- Exact file paths always. Complete code in every code step. Exact commands with expected output. DRY, YAGNI, TDD, frequent commits.

## Self-Review

After writing the plan, check it against the spec with fresh eyes (a checklist you run yourself):
1. **Spec coverage:** skim each requirement — can you point to a task that implements it? List gaps.
2. **Placeholder scan:** search for the red flags above. Fix them.
3. **Type consistency:** do types/signatures/names in later tasks match earlier ones? (`clearLayers()` in Task 3 vs `clearFullLayers()` in Task 7 is a bug.)

Fix issues inline. If a spec requirement has no task, add the task.

## Execution Handoff

After saving the plan, offer the execution choice:

> "Plan complete and saved to `docs/plans/<filename>.md`. Two execution options:
> **1. Subagent-Driven (recommended)** — a fresh subagent per task, review between tasks, fast iteration.
> **2. Inline Execution** — execute tasks in this session with executing-plans, batched with checkpoints.
> Which approach?"

- **Subagent-Driven →** use the subagent-driven-development skill (fresh subagent per task + two-stage review).
- **Inline →** use the executing-plans skill (batched execution with review checkpoints).
