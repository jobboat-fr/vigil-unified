# VIGIL × WinnyWoo — Unified Build Log

A living journal of the mining/adaptation work. **Every step:** what was done + where it's heading. Newest entries at the bottom of each section.

## Sources (cloned to `~/vigil-refs/`, reference only — we mine, we don't run their runtimes)
| Repo | Mine for | Lands in |
|---|---|---|
| `obra/superpowers` | brainstorm/think/plan/verify methodology + session-start hook | `skills/thinking/` + a Hermes hook / persona rule |
| `MikeChongCan/cfo-stack` | finance/fiscal skills (Beancount-based) | `skills/finance/` |
| `coreyhaines31/marketingskills` | marketing skills | `skills/marketing/` |
| `frappe/crm` | CRM data model + lifecycle flows (Frappe app — extract, don't run) | `skills/crm/` + data model + tool |
| `mailpile/Mailpile` | triage intelligence (spambayes/tagging) over the himalaya transport | `skills/mail/` |

## Method per skill (one at a time)
1. **Read** the source skill.
2. **Adapt** → fork frontmatter (`name`, `description`, `version`, `author: VIGIL × WinnyWoo`, `license: MIT`, `metadata.hermes.tags`/`related_skills`); strip foreign-runtime assumptions (Claude-Code plugin paths, Beancount-CLI-only, slash-command-only); keep the hard-gates / enforced behaviors; repath defaults (`docs/superpowers/specs/` → `docs/specs/`). Curate, don't dump.
3. **Route** — ask *where in the product is this useful?* and record the target functionalities it should plug into (Meeting Room, Studio/Artifacts, Vault, Council, Trade Desk, Signals, Calculations, Chat, global persona). Two flavors: **global** (bake into SOUL/persona as an always-on behavior) vs **feature** (a specific flow invokes it).
4. **Log** the step (what changed + Routes-to + next).
> Wiring the routes into the actual flows happens as each product flow is built; the routing decision is recorded now so nothing is an orphan skill.

## Routing targets (product functionalities skills plug into)
Meeting Room · Studio/Artifacts · Vault · Council · Trade Desk · Signals/Analysis · Calculations/Models · Chat · global persona (SOUL.md/AGENTS.md).

## Adaptation rules (applied to every mined skill)
1. Frontmatter → fork format. 2. Strip tool-specific assumptions. 3. Keep hard-gates. 4. Repath defaults. 5. Curate, don't dump.

## Progress

### 2026-06-15 — Setup
- Cloned all 5 reference repos to `~/vigil-refs/` (superpowers, cfo-stack, marketingskills, crm, Mailpile). Read structure + representative skills; confirmed the 3 skills repos use agentskills.io frontmatter (drop-in compatible with the fork's loader).
- Created domain folders under `skills/`: `thinking/`, `finance/`, `marketing/`, `crm/`, `mail/`.
- **Heading:** start with the `thinking` domain (superpowers) — your lead ask ("forcefully brainstorm + think on each functionality"), highest leverage because it shapes how every later feature gets built.

### thinking/ (from superpowers) — curated set
Target skills (13 in source; curating to the ones that fit a product-building agent):
`brainstorming`, `writing-plans`, `executing-plans`, `verification-before-completion`, `systematic-debugging`, `subagent-driven-development`, `requesting-code-review`, `receiving-code-review`. (Skipping `using-git-worktrees`, `finishing-a-development-branch`, `using-superpowers`, `writing-skills`, `dispatching-parallel-agents` for now — git/meta-specific; revisit later.)

- [x] **brainstorming** — adapted → `skills/thinking/brainstorming/`. Kept the `<HARD-GATE>` (no implementation before an approved design) + one-question-at-a-time checklist + process flow. Repathed specs; trimmed the Claude-only visual-companion link. **Core of "force the agent to think first."**
  - **Routes to →** **Studio/Artifacts** (brainstorm the artifact's shape before drafting — when assisting in a meeting or solo), **Meeting Room** (when the agent proposes building something mid-session, spec it first), **Calculations/Models** (brainstorm a financial/trading model before computing), **Trade Desk** (brainstorm a new strategy before writing its algorithm), and any "build me X" in **Chat**. Wiring: Studio "create/refine artifact" flow invokes it first; persona rule that creative requests trigger it.
- [x] **writing-plans** — adapted → `skills/thinking/writing-plans/`. Kept bite-sized TDD task structure, no-placeholders rule, self-review, execution handoff. Repathed to `docs/plans/`; dropped `superpowers:` prefixes; removed worktree note.
  - **Routes to →** any **multi-step build**: a new WinnyWoo **strategy/algorithm**, a new **skill/tool**, a Council **action-item → project**, a Studio **multi-section artifact**. Wiring: brainstorming hands off to it; persona rule that non-trivial builds get a plan before code.
- [x] **verification-before-completion** — adapted → `skills/thinking/verification-before-completion/`. Near-verbatim (pure discipline: "no completion claims without fresh verification evidence"). Condensed prose + frontmatter.
  - **Routes to →** **GLOBAL** (bake into SOUL.md/AGENTS.md as an always-on gate): every "done/fixed/passing" claim — **trade-execution** confirmations, **artifact** completion, **strategy/code** changes, **audit** assertions, **meeting summaries**. Not a single feature; a universal pre-claim gate.
- [x] **executing-plans** — adapted → `skills/thinking/executing-plans/`. Kept critical-review-first, stop-on-blocker, branch-not-main rule. Replaced `superpowers:finishing-a-development-branch` (git-meta, not curated) with our `verification-before-completion` as the completion gate; generalized worktree + the "use Claude Code/Codex for subagents" note.
  - **Routes to →** the **implementation phase of any build** (after writing-plans): new strategies, skills, tools, artifacts, features. Global agent build-discipline; pairs with subagent-driven-development.
- [x] **subagent-driven-development** — adapted → `skills/thinking/`. Kept per-task loop + two-stage review (spec→quality) + model selection + status handling + red flags. Repointed `superpowers:` refs to our bare skill names; replaced `finishing-a-development-branch` with `verification-before-completion`; inlined the prompt-template guidance (the `./*-prompt.md` files weren't curated).
  - **Routes to →** implementation phase of multi-task builds (new strategies, skills, features in the unified project). Global dev flow; preferred over executing-plans when subagents are available.
- [x] **systematic-debugging** — adapted → `skills/thinking/`. Kept the Iron Law + four phases + 3-fixes→question-architecture rule + red flags. Tool-agnostic; "human partner" → "the user"; dropped missing supporting-file links (folded the technique inline).
  - **Routes to →** **GLOBAL** — any bug/failure anywhere: Trade Desk data, signal-runner errors, agent tool failures, build failures. Always invoked before proposing a fix.
- [x] **requesting-code-review** — adapted → `skills/thinking/`. Kept when/how/act-on-feedback; generalized the missing template to "dispatch a reviewer with crafted context"; cross-linked our `/code-review` (+ ultra).
  - **Routes to →** before merging any feature/strategy/skill; pairs with the platform `/code-review`.
- [x] **receiving-code-review** — adapted → `skills/thinking/`. Kept verify-before-implement, no-performative-agreement, YAGNI, pushback rules. "human partner" → "the user".
  - **Routes to →** **GLOBAL** — whenever the agent receives review feedback (from the user or `/code-review`).

#### ✅ thinking/ COMPLETE — 8 of 8 curated done.
**Global-persona wiring pending:** `verification-before-completion`, `systematic-debugging`, `receiving-code-review`, and brainstorm-first need to be baked into vigil-unified's SOUL.md/AGENTS.md as always-on behaviors (do this when we assemble the unified persona).
- **Next domain → `finance/` (cfo-stack):** curating ~8 of 30 — `cfo` (router), `advisor`, `capture`, `classify`, `reconcile`, `monthly-close`, `quarterly-tax`/`tax-plan`, `report`. Adapt off Beancount-CLI specifics toward our vault + finance tools.
