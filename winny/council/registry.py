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
    """Resolved at call time so env overrides (and tests) take effect."""
    return {
        "primary": {
            "provider": "Anthropic",
            "model": os.getenv("COUNCIL_PRIMARY_MODEL") or os.getenv("ANTHROPIC_MODEL") or "claude-sonnet-4-5-20250929",
            "family": "anthropic",
            "specialization": "ROLE_SPECIALIST",
            "voteWeight": 1.5,
            "enabled": True,
        },
        "reviewer_1": {
            "provider": "OpenAI",
            "model": os.getenv("COUNCIL_REVIEWER_1_MODEL") or "gpt-4o",
            "family": "openai",
            "specialization": "BALANCED_REVIEWER",
            "voteWeight": 1.3,
            "enabled": True,
        },
        "reviewer_2": {
            "provider": "Google",
            "model": os.getenv("COUNCIL_REVIEWER_2_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash",
            "family": "google",
            "specialization": "FAST_REVIEWER",
            "voteWeight": 1.2,
            "enabled": True,
        },
        "chairman": {
            "provider": "Google",
            "model": os.getenv("COUNCIL_CHAIRMAN_MODEL") or "gemini-2.5-flash",
            "family": "google",
            "specialization": "CHAIRMAN",
            "voteWeight": 2.0,
            "enabled": True,
        },
    }


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
