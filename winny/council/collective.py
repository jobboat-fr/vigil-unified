"""AI Worker Collective — Python port of VIGIL's aiWorkerCollective.js.

5-stage council flow:
  1. Primary worker produces an answer (role-specialist).
  2. Reviewers (different model families) score it in JSON — run in parallel.
  3. Weighted consensus voting.
  4. Chairman synthesizes a final decision IFF consensus fails.
  5. (optional) Behavioral pattern overlay — wired via ``behavioral_hook``;
     omitted by default (the 572-pattern registry is a separate subsystem).

Returns the same telemetry ``record`` shape the VIGIL frontend/clients expect:
``{run_id, task, scenario_id, timestamp, stages, totals, verdict}``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from winny.council.providers import ask
from winny.council.registry import TASK_MATRIX, worker_registry
from winny.council.scoring import (
    compute_weighted_overall,
    parse_review_scores,
    try_parse_intervention,
)

# emit(stage: str, data: dict) -> None  (sync or async)
EmitFn = Callable[[str, dict[str, Any]], Any]
BehavioralHook = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any] | None]]


class AIWorkerCollective:
    def __init__(
        self,
        workers: dict[str, dict[str, Any]] | None = None,
        tasks: dict[str, dict[str, Any]] | None = None,
        *,
        consensus_threshold: float = 0.66,
        readiness_threshold: float = 0.80,
        behavioral_hook: BehavioralHook | None = None,
    ) -> None:
        self.workers = workers or worker_registry()
        self.tasks = tasks or TASK_MATRIX
        self.consensus_threshold = consensus_threshold
        self.readiness_threshold = readiness_threshold
        self.behavioral_hook = behavioral_hook

    async def orchestrate(
        self,
        task_type: str,
        scenario: dict[str, Any],
        *,
        emit: EmitFn | None = None,
    ) -> dict[str, Any]:
        task_cfg = self.tasks.get(task_type)
        if not task_cfg:
            raise ValueError(f"Unknown task: {task_type}")

        run_id = str(uuid.uuid4())
        start_total = time.time()
        record: dict[str, Any] = {
            "run_id": run_id,
            "task": task_type,
            "scenario_id": scenario.get("id"),
            "timestamp": datetime.now(UTC).isoformat(),
            "stages": {},
            "totals": {},
            "verdict": {},
        }

        await self._emit(emit, "start", {"task": task_type, "scenario_id": scenario.get("id")})

        # ── Stage 1: primary ────────────────────────────────────────────
        primary_worker = self.workers[task_cfg["primaryWorker"]]
        primary_user = self._resolve_prompt(scenario.get("primaryUserPrompt"), scenario)
        primary_resp = await ask(
            primary_worker, primary_user,
            system=scenario.get("primarySystemPrompt"), temperature=0.3, max_tokens=600,
        )
        record["stages"]["primary"] = {
            "worker_role": task_cfg["primaryWorker"],
            "model": primary_worker["model"],
            "family": primary_worker["family"],
            "output": primary_resp["output"],
            "usage": primary_resp["usage"],
            "cost_usd": primary_resp["cost_usd"],
            "latency_ms": primary_resp["latency_ms"],
            "finish_reason": primary_resp["finish_reason"],
            "parsed_intervention": try_parse_intervention(primary_resp["output"]),
        }
        await self._emit(emit, "primary_done", {
            "worker_role": task_cfg["primaryWorker"], "model": primary_worker["model"],
            "latency_ms": primary_resp["latency_ms"], "cost_usd": primary_resp["cost_usd"],
            "parsed": record["stages"]["primary"]["parsed_intervention"]["parsed"],
        })

        # ── Stage 2: reviewers (parallel) ───────────────────────────────
        reviewer_keys = task_cfg.get("reviewers", [])

        async def review(rev_key: str) -> dict[str, Any]:
            rev = self.workers[rev_key]
            user_prompt = self._reviewer_prompt(scenario, primary_resp["output"])
            resp = await ask(
                rev, user_prompt,
                system=scenario.get("reviewerSystemPrompt"), temperature=0.2, max_tokens=800,
            )
            scores = parse_review_scores(resp["output"])
            result = {
                "reviewer_role": rev_key, "model": rev["model"], "family": rev["family"],
                "scores": scores, "usage": resp["usage"], "cost_usd": resp["cost_usd"],
                "latency_ms": resp["latency_ms"], "raw_output": resp["output"],
            }
            await self._emit(emit, "reviewer_done", {
                "reviewer_role": rev_key, "model": rev["model"],
                "overall": scores["overall"], "latency_ms": resp["latency_ms"],
            })
            return result

        reviews = await asyncio.gather(*(review(k) for k in reviewer_keys))
        record["stages"]["reviews"] = list(reviews)

        # ── Stage 3: consensus voting ───────────────────────────────────
        voting = self._compute_voting(primary_worker, reviews, task_cfg)
        record["stages"]["voting"] = voting
        await self._emit(emit, "consensus_result", {
            "consensus": voting["consensus"], "agreement_rate": voting["agreement_rate"],
            "weighted_overall": voting["weighted_overall"],
        })

        # ── Stage 4: chairman (only if consensus fails) ─────────────────
        chairman_resp = None
        if not voting["consensus"]:
            chairman = self.workers[task_cfg["chairman"]]
            chairman_user = self._chairman_prompt(scenario, primary_resp["output"], reviews)
            chairman_resp = await ask(
                chairman, chairman_user,
                system="You are the Chairman of an AI council. Synthesize a final decision when reviewers disagree. Output the same JSON schema as the primary advisor.",
                temperature=0.2, max_tokens=600,
            )
            record["stages"]["chairman"] = {
                "worker_role": task_cfg["chairman"], "model": chairman["model"], "family": chairman["family"],
                "output": chairman_resp["output"],
                "parsed_intervention": try_parse_intervention(chairman_resp["output"]),
                "usage": chairman_resp["usage"], "cost_usd": chairman_resp["cost_usd"],
                "latency_ms": chairman_resp["latency_ms"], "triggered_because": "consensus_failed",
            }
            await self._emit(emit, "chairman_done", {
                "model": chairman["model"], "latency_ms": chairman_resp["latency_ms"],
                "cost_usd": chairman_resp["cost_usd"],
                "parsed": record["stages"]["chairman"]["parsed_intervention"]["parsed"],
            })

        # ── Stage 5: behavioral overlay (optional hook) ─────────────────
        if task_cfg.get("behaviorPatternsEnabled") and scenario.get("transcript") and self.behavioral_hook:
            try:
                behavioral = await self.behavioral_hook(scenario["transcript"], task_cfg)
                if behavioral:
                    record["stages"]["behavioral"] = behavioral
                    await self._emit(emit, "behavioral_done", {
                        "n_speakers": behavioral.get("n_speakers_analysed"),
                        "n_patterns": behavioral.get("n_patterns_total"),
                    })
            except Exception:  # behavioral overlay must never fail the council
                pass

        # ── Stage 6: verdict + totals ───────────────────────────────────
        final_intervention = (
            record["stages"]["chairman"]["parsed_intervention"] if chairman_resp
            else record["stages"]["primary"]["parsed_intervention"]
        )
        record["verdict"] = {
            "consensus_reached": voting["consensus"],
            "readiness_pass": voting["weighted_overall"] >= (task_cfg["readinessThreshold"] * 100),
            "readiness_score": voting["weighted_overall"],
            "chairman_invoked": bool(chairman_resp),
            "final_intervention": final_intervention,
            "behavioral_signals": (record["stages"].get("behavioral") or {}).get("signals_summary"),
        }

        all_calls = [record["stages"]["primary"], *record["stages"]["reviews"]]
        if chairman_resp:
            all_calls.append(record["stages"]["chairman"])
        record["totals"] = {
            "tokens_in": sum(c.get("usage", {}).get("prompt_tokens", 0) for c in all_calls),
            "tokens_out": sum(c.get("usage", {}).get("completion_tokens", 0) for c in all_calls),
            "cost_usd": round(sum(c.get("cost_usd", 0) for c in all_calls), 6),
            "latency_ms_total": int((time.time() - start_total) * 1000),
            "latency_ms_sum_calls": sum(c.get("latency_ms", 0) for c in all_calls),
            "n_llm_calls": len(all_calls),
        }
        return record

    # ── internals ───────────────────────────────────────────────────────

    def _compute_voting(self, primary_worker, reviews, task_cfg) -> dict[str, Any]:
        approve = 0.0
        reject = 0.0
        overall_scores: list[float] = []
        for rev in reviews:
            reviewer = self.workers.get(rev["reviewer_role"]) or {}
            w = reviewer.get("voteWeight", 1.0)
            overall = rev["scores"]["overall"]
            overall_scores.append(overall)
            if overall >= 70:
                approve += w
            else:
                reject += w
        approve += primary_worker["voteWeight"] * 0.5  # primary self-confidence, half weight
        total = approve + reject
        agreement = approve / total if total > 0 else 0.0
        consensus = agreement >= self.consensus_threshold
        mean = sum(overall_scores) / (len(overall_scores) or 1)
        variance = sum((v - mean) ** 2 for v in overall_scores) / (len(overall_scores) or 1)
        weighted = [compute_weighted_overall(r["scores"]) for r in reviews]
        weighted_overall = sum(weighted) / (len(weighted) or 1)
        return {
            "consensus": consensus,
            "agreement_rate": round(agreement, 3),
            "approve_votes": round(approve, 2),
            "reject_votes": round(reject, 2),
            "reviewer_overall_scores": overall_scores,
            "reviewer_weighted_scores": [round(s, 1) for s in weighted],
            "mean_overall": round(mean, 1),
            "stddev_overall": round(variance ** 0.5, 2),
            "weighted_overall": round(weighted_overall, 1),
        }

    @staticmethod
    def _resolve_prompt(prompt: Any, scenario: dict[str, Any]) -> str:
        if callable(prompt):
            return prompt()
        if isinstance(prompt, str) and prompt:
            return prompt.replace("{transcript}", scenario.get("transcript", ""))
        return (
            f"Meeting transcript:\n\n{scenario.get('transcript', '')}\n\n"
            "What is your intervention? Respond ONLY with the JSON object."
        )

    @staticmethod
    def _reviewer_prompt(scenario: dict[str, Any], primary_output: str) -> str:
        tpl = scenario.get("reviewerUserPrompt")
        if callable(tpl):
            return tpl(scenario.get("transcript", ""), primary_output)
        if isinstance(tpl, str) and tpl:
            return tpl.replace("{transcript}", scenario.get("transcript", "")).replace("{primary}", primary_output)
        return (
            f"Meeting transcript:\n\n{scenario.get('transcript', '')}\n\n"
            f"Proposed intervention (JSON):\n{primary_output}\n\n"
            "Score it. Respond ONLY with the JSON object."
        )

    @staticmethod
    def _chairman_prompt(scenario: dict[str, Any], primary_output: str, reviews) -> str:
        summaries = "\n".join(
            f"- {r['reviewer_role']} ({r['model']}): overall={r['scores']['overall']}, "
            f"accuracy={r['scores']['accuracy']}, relevance={r['scores']['relevance']}, "
            f"harm_risk={r['scores']['harm_risk']}, reasoning=\"{r['scores'].get('reasoning') or 'n/a'}\""
            for r in reviews
        )
        return (
            f"Meeting transcript:\n\n{scenario.get('transcript', '')}\n\n"
            f"Primary advisor proposed (JSON):\n{primary_output}\n\n"
            f"Reviewers scored:\n{summaries}\n\n"
            "The reviewers did not reach 66% consensus. Synthesize a FINAL decision yourself.\n"
            "Respond ONLY with the same JSON schema as the primary advisor:\n"
            '{"should_intervene": boolean, "intervention_text": "...", '
            '"category": "...", "confidence": 0-100, "reasoning": "..."}'
        )

    @staticmethod
    async def _emit(emit: EmitFn | None, stage: str, data: dict[str, Any]) -> None:
        if emit is None:
            return
        result = emit(stage, {"ts": int(time.time() * 1000), **data})
        if asyncio.iscoroutine(result):
            await result
