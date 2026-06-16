# AZZCO LLM architecture — debrief + port into vigil-unified

Notes from dissecting the original multi-LLM stack on the OVH host
(`/opt/azzco-council/core`, Node), and how it's being applied here.

## How the original is built (OVH `azzco-council`)

A **cost-aware, task-hardness model router** over HuggingFace + Together, not a
single model. Five layers:

1. **Providers** (`src/providers/`)
   - `huggingface_chat_provider.js` → `https://router.huggingface.co/v1/chat/completions`
     (OpenAI-compatible) with `Authorization: Bearer HF_TOKEN` **and
     `x-hf-bill-to: <org>`** to bill inference to the org wallet. `response_format:
     json_object`, temp 0.2. **Falls back to a MockProvider on any error** (no
     token / timeout / non-2xx / bad JSON) so a run never crashes.
   - `huggingface_provider.js` → the classic Inference API for **free** task models
     (zero-shot classify `facebook/bart-large-mnli`, sentiment
     `cardiffnlp/twitter-roberta`, emotion `SamLowe/roberta-base-go_emotions`,
     summarizer `distilbart`). costRank 0.
   - `together_provider.js`, `mock_provider.js`, `provider_registry.js`
     (mode via `AZZCO_LIVE_PROVIDER_MODE`).

2. **Model registry** (`config/model_registry.js`) — aliases tiered by **costRank
   + privacy + strengths**: `hf-zero-shot/sentiment/emotion/summarizer` (rank 0,
   free) · `cheap-default` (rank 1, gpt-oss-120b) · `business-workhorse` (rank 2)
   · `ovh-legal/accounting/cto-specialist` (rank 3, high-privacy, some local vLLM)
   · `premium-judge` (rank 4). Many aliases share one model (gpt-oss-120b) but are
   tiered for routing + accounting.

3. **Task router** (`router/task_router.js`) — classifies a request into one of
   ~25 categories by keyword (incident_watchdog, mail_triage, sales_reply,
   legal_accounting, cto_audit, lead_scout…), infers **urgency P0–P3**, a
   **restricted** flag (legal/finance/confidential keywords), and decides
   `requireCouncil` + `requireOwnerApproval`.

4. **Task matrix** (`config/task_matrix.js`) — per category: `defaultModel`,
   `council` (worker roles), `judge` (model alias), `maxInputTokens`,
   `ownerApproval`, `criticality`. High-stakes → `premium-judge`; trivial →
   `cheap-default`. Workers defined in `config/worker_architecture.js`.

5. **Cost economics** (`ops/`) — the heart:
   - `utils/token_estimator.js`: tokens ≈ `chars / 4`.
   - `ops/cost_guard.js`: `TOKEN_PRICES_USD_PER_1M` per model (gpt-oss-120b
     $0.15/$0.60, gpt-oss-20b $0.05/$0.20, Kimi-K2 $0.50/$2.80, free models $0).
     **`planFor(route)` returns a multi-step plan per category** with
     `multiplier`/`inputRatio`/`outputRatio` + a `reason` — e.g. mail_labeling =
     free zero-shot + 0.25× cheap fallback; cold_email = 0.7× cheap draft + 0.3×
     workhorse escalation; sales_reply = workhorse + selective premium judge
     (0.45× if P0 else 0.15×); legal = cheap extract + restricted specialist.
   - `CostGuard.evaluate()`: daily/monthly/hard-stop budgets ($6/$180/$8) +
     per-provider daily caps ($3 HF, $3 Together). Over budget → **`force_cheap`**
     (downgrade the whole plan to cheap-default) or **`hard_stop`**.
     `AZZCO_FORCE_CHEAP_MODE` env override.
   - `ops/budget_store.js`: tracks planned + **actual** USD/day/month/provider;
     `recordActual` charges real usage tokens after each call.
   - `ops/route_logger.js`: logs every routing decision.

**The economic idea:** route each task to the *cheapest adequate* tier; do free
classification/sentiment/summary on rank-0 HF models; cheap-extract-then-
selectively-escalate; cap spend with auto-downgrade; bill to the org wallet.

## What we ported now (keystone)

Goal: make our council/Studio/Mail run on **one HF key** instead of three
missing native keys (ANTHROPIC/OPENAI/GOOGLE were all unset on Railway → every
LLM feature was stubbed).

- `winny/council/providers.py`: added a **`huggingface`/`hf` family** in `ask()`
  → HF router (OpenAI-compatible) with `Authorization: Bearer HF_TOKEN` +
  `x-hf-bill-to` (defaults to **`azzetco`** — the real org; the handoff's
  `jobboat` was a wrong guess that 403'd). `_call_openai` now takes
  `extra_headers`. Added HF model prices to the cost table.
- `winny/council/registry.py`: the 4 workers now default to HF
  (`COUNCIL_PROVIDER=huggingface`): primary/reviewer_1/chairman → `openai/gpt-oss-120b`,
  reviewer_2 → `openai/gpt-oss-20b` (cheap fast lane). `COUNCIL_PROVIDER=anthropic|
  openai|google` reverts; `COUNCIL_*_MODEL` pins models.
- **Verified live** through `ask()`: 120b + 20b both return real output
  (stub=False) via the router, cost telemetry ≈ $0.00005/call.

This is the minimal cut. The richer AZZCO layers (task-hardness `planFor`
routing + `CostGuard` budget guards + free rank-0 classifiers for Mail triage)
are the next enhancement — see below.

## Findings / corrections
- **HF org is `azzetco`, not `jobboat`** (handoff §5.4 was a guess). Personal
  account is out of included credits; the `azzetco` org wallet has them — so
  `x-hf-bill-to: azzetco` is required.
- Same correction should be applied to the **OVH `.env`** (`HF_BILL_TO=jobboat`
  → `azzetco`) for the winnywoo/vigil-hermes containers, or their chat will hit
  the same credit error.

## Next (enhancement backlog)
1. Port `cost_guard` + `model_registry` tiers as `winny/llm/economics.py`; add a
   `plan_for(task)` so Studio/Council/Mail pick a tier by hardness.
2. Use **free rank-0 HF classifiers** for Mail triage (`bart-large-mnli`
   zero-shot) instead of a full chat call — near-zero cost.
3. Budget guard (daily/monthly caps + force-cheap) with a Supabase-backed
   budget store.
4. Wire the OVH/vigil-hermes agent provider to HF+azzetco via the Hermes CLI.
