"""Council worker registry + task-specialization matrix — Python port of
VIGIL's workerRegistry.js and taskSpecializationMatrix.js.

The 4-worker shape (1 primary + 2 reviewers + 1 chairman) spans three model
families (Anthropic / OpenAI / Google) to avoid bias collapse. The role lens
(CFO / Tech / Legal / Product) is applied at the TASK level via per-scenario
system prompts; the same workers serve every role.
"""

from __future__ import annotations

import os
from typing import Any


def worker_registry() -> dict[str, dict[str, Any]]:
    """Resolved at call time so env overrides (and tests) take effect.

    Fournisseur par défaut : **Together** (``TOGETHER_API_KEY``) depuis le 2026-09-17 — les
    crédits Hugging Face sont épuisés, et les agents AZZCOM/AZZCO/AZZMIN tournent déjà sur
    Together. Modèles vérifiés en appel direct ce jour-là : GLM-5.3 pour le raisonnement
    principal et la synthèse, DeepSeek-V4-Pro et gpt-oss-120b pour les deux relectures
    (trois familles différentes, pour limiter l'effondrement des biais).

    ``COUNCIL_PROVIDER`` = ``huggingface`` / ``anthropic`` / ``openai`` / ``google`` pour
    revenir en arrière ; ``COUNCIL_*_MODEL`` pour épingler un modèle.
    """
    fam = os.getenv("COUNCIL_PROVIDER", "together").lower()
    defaults = _DEFAULT_MODELS.get(fam, _DEFAULT_MODELS["_other"])
    prov = {"huggingface": "HuggingFace", "hf": "HuggingFace"}.get(fam, fam.title())

    def worker(slot: str, env: str, specialization: str, weight: float) -> dict[str, Any]:
        return {
            "provider": prov,
            "model": os.getenv(env) or defaults[slot],
            "family": fam,
            "specialization": specialization,
            "voteWeight": weight,
            "enabled": True,
        }

    return {
        "primary": worker("primary", "COUNCIL_PRIMARY_MODEL", "ROLE_SPECIALIST", 1.5),
        "reviewer_1": worker("reviewer_1", "COUNCIL_REVIEWER_1_MODEL", "BALANCED_REVIEWER", 1.3),
        "reviewer_2": worker("reviewer_2", "COUNCIL_REVIEWER_2_MODEL", "FAST_REVIEWER", 1.2),
        "chairman": worker("chairman", "COUNCIL_CHAIRMAN_MODEL", "CHAIRMAN", 2.0),
    }


_HF_MODELS = {
    "primary": "openai/gpt-oss-120b", "reviewer_1": "openai/gpt-oss-120b",
    "reviewer_2": "openai/gpt-oss-20b", "chairman": "openai/gpt-oss-120b",
}
_DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "together": {
        "primary": "zai-org/GLM-5.3", "reviewer_1": "deepseek-ai/DeepSeek-V4-Pro-0813",
        "reviewer_2": "openai/gpt-oss-120b", "chairman": "zai-org/GLM-5.3",
    },
    "huggingface": _HF_MODELS,
    "hf": _HF_MODELS,
    "_other": {
        "primary": os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-5-20250929", "reviewer_1": "gpt-4o",
        "reviewer_2": os.getenv("GEMINI_MODEL") or "gemini-2.5-flash", "chairman": "gemini-2.5-flash",
    },
}


def cheap_worker() -> dict[str, Any]:
    """A cheap, high-volume classifier worker.

    When a local OpenAI-compatible model is configured (``LOCAL_LLM_BASE``, e.g. a
    llama.cpp/Ollama server), routine classification (mail triage, transaction
    categorisation, lead scoring) runs there for ~$0 instead of the metered council
    model — the council stays for hard reasoning. Falls back to the primary worker
    when no local model is set, so callers can always use it safely (no-op default).
    """
    if os.getenv("LOCAL_LLM_BASE"):
        return {
            "provider": "Local",
            "model": os.getenv("LOCAL_LLM_MODEL") or "local-model",
            "family": "local",
            "specialization": "CHEAP_CLASSIFIER",
            "voteWeight": 1.0,
            "enabled": True,
        }
    return worker_registry()["primary"]


def _worker_from_spec(spec: str) -> dict[str, Any]:
    """Parse a cheap-pool spec like 'local', 'groq:llama-3.1-8b-instant',
    'hf:openai/gpt-oss-20b' into a worker dict."""
    spec = spec.strip()
    fam, _, model = spec.partition(":")
    fam = (fam or "").lower()
    if fam == "local":
        return {"provider": "Local", "family": "local",
                "model": model or os.getenv("LOCAL_LLM_MODEL") or "local-model", "voteWeight": 1.0, "enabled": True}
    if fam in ("hf", "huggingface"):
        return {"provider": "HuggingFace", "family": "huggingface",
                "model": model or "openai/gpt-oss-20b", "voteWeight": 1.0, "enabled": True}
    return {"provider": fam.title(), "family": fam, "model": model, "voteWeight": 1.0, "enabled": True}


def cheap_pool() -> list[dict[str, Any]]:
    """Ordered list of cheap providers for high-volume classification, tried with
    failover by ``providers.ask_cheap``.

    ``CHEAP_POOL`` (comma-separated specs) overrides; otherwise: a local model first
    (if ``LOCAL_LLM_BASE`` is set), then a paid-cheap Together fallback so there is always a
    working tier. Commercial note: free third-party tiers must not serve paying
    tenants (ToS) — keep those out of the pool when serving customers.
    """
    raw = os.getenv("CHEAP_POOL", "").strip()
    if raw:
        return [_worker_from_spec(s) for s in raw.split(",") if s.strip()]
    pool: list[dict[str, Any]] = []
    if os.getenv("LOCAL_LLM_BASE"):
        pool.append(_worker_from_spec("local"))
    pool.append(_worker_from_spec(f"together:{os.getenv('CHEAP_TOGETHER_MODEL', 'deepseek-ai/DeepSeek-V4.1-Flash')}"))
    return pool


_COMMON = {
    "primaryWorker": "primary",
    "reviewers": ["reviewer_1", "reviewer_2"],
    "chairman": "chairman",
    "consensusThreshold": 0.66,
    "readinessThreshold": 0.80,
    "slaMs": 15_000,
    "behaviorPatternsEnabled": True,
    "outputSchema": {
        "should_intervene": "boolean",
        "intervention_text": "string (2-3 sentences)",
        "category": "string (role-specific category)",
        "confidence": "number 0-100",
        "reasoning": "string",
    },
}


def _task(**over: Any) -> dict[str, Any]:
    return {**_COMMON, **over}


TASK_MATRIX: dict[str, dict[str, Any]] = {
    "cfo_review": _task(
        description="CFO advisor reviews a meeting transcript: budget conflicts, runway, ROI, financial risk, compliance cost.",
        requirements=["financial_judgment", "tone_collaboration", "risk_awareness"],
        categories=["budget", "cashflow", "compliance_cost", "roi", "pricing", "forecast", "audit", "other"],
        pattern_focus=["confidence", "authenticity", "integrity", "stress", "critical", "systemic"],
    ),
    "tech_review": _task(
        description="Tech advisor reviews a meeting transcript: architecture, scaling, technical debt, security, observability gaps.",
        requirements=["technical_judgment", "tone_engineer", "risk_aware"],
        categories=["architecture", "scaling", "security", "tech_debt", "observability", "incident", "tooling", "other"],
        pattern_focus=["technical", "cognitive", "critical", "systemic", "communication", "stress"],
    ),
    "legal_review": _task(
        description="Legal advisor reviews a meeting transcript: contract risk, GDPR, IP, compliance, employment law.",
        requirements=["legal_judgment", "tone_precise", "risk_high"],
        categories=["gdpr", "contract", "ip", "employment", "compliance", "audit_trail", "other"],
        pattern_focus=["integrity", "critical", "authenticity", "communication", "systemic"],
    ),
    "product_review": _task(
        description="Product advisor reviews a meeting transcript: UX coherence, scope creep, prioritisation, customer impact.",
        requirements=["product_judgment", "tone_curious", "user_first"],
        categories=["scope", "ux", "prioritisation", "customer_value", "metric_misalignment", "tech_user_gap", "other"],
        pattern_focus=["communication", "creativity", "critical", "listening", "authenticity", "feedback"],
    ),
}

# Default per-role system prompts so a room can run a lens without a bespoke
# scenario file. Mirrors the role intent encoded in the task matrix.
ROLE_SYSTEM_PROMPTS: dict[str, str] = {
    "cfo_review": "You are a seasoned CFO advisor on an AI council. Review the meeting transcript for budget, runway, ROI, pricing, and financial/compliance risk. Respond ONLY with the JSON object: {\"should_intervene\": boolean, \"intervention_text\": \"2-3 sentences\", \"category\": one of the CFO categories, \"confidence\": 0-100, \"reasoning\": \"...\"}.",
    "tech_review": "You are a principal engineer / CTO advisor on an AI council. Review the transcript for architecture, scaling, security, tech debt, and observability gaps. Respond ONLY with the JSON object: {\"should_intervene\": boolean, \"intervention_text\": \"2-3 sentences\", \"category\": one of the tech categories, \"confidence\": 0-100, \"reasoning\": \"...\"}.",
    "legal_review": "You are a precise legal/compliance advisor on an AI council. Review the transcript for contract risk, GDPR, IP, employment, and compliance exposure. Respond ONLY with the JSON object: {\"should_intervene\": boolean, \"intervention_text\": \"2-3 sentences\", \"category\": one of the legal categories, \"confidence\": 0-100, \"reasoning\": \"...\"}.",
    "product_review": "You are a customer-obsessed product advisor on an AI council. Review the transcript for UX coherence, scope creep, prioritisation, and customer impact. Respond ONLY with the JSON object: {\"should_intervene\": boolean, \"intervention_text\": \"2-3 sentences\", \"category\": one of the product categories, \"confidence\": 0-100, \"reasoning\": \"...\"}.",
}

REVIEWER_SYSTEM_PROMPT = (
    'You are a peer reviewer. Score the proposed intervention 0-100 on accuracy, '
    'relevance, completeness, tone, harm_risk, timing, overall. Respond ONLY with '
    'JSON: {"accuracy":0-100,"relevance":0-100,"completeness":0-100,"tone":0-100,'
    '"harm_risk":0-100,"timing":0-100,"overall":0-100,"reasoning":"..."}'
)
