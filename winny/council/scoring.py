"""Score parsing for the AI council — Python port of VIGIL's score_parser.js.

Extracts structured JSON scores from a reviewer LLM's output, robust to code
fences, surrounding prose, trailing commas, and missing fields (filled with a
neutral 70). Also computes the V2 weighted-overall rubric.
"""

from __future__ import annotations

import json
import re
from typing import Any

SCORE_FIELDS = ["accuracy", "relevance", "completeness", "tone", "harm_risk"]

# V2 weighted rubric (0-100).
WEIGHTS: dict[str, float] = {
    "accuracy": 0.30,
    "relevance": 0.20,
    "harm_risk": 0.20,
    "completeness": 0.15,
    "timing": 0.10,
    "tone": 0.05,
}

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def extract_json_object(text: str | None) -> dict[str, Any] | None:
    """Extract the first JSON object from a string (fence/prose tolerant)."""
    if not text:
        return None
    fenced = _FENCE_RE.search(text)
    candidate = fenced.group(1) if fenced else text
    first = candidate.find("{")
    last = candidate.rfind("}")
    if first == -1 or last == -1 or last < first:
        return None
    slice_ = candidate[first : last + 1]
    try:
        obj = json.loads(slice_)
    except json.JSONDecodeError:
        cleaned = _TRAILING_COMMA_RE.sub(r"\1", slice_)
        try:
            obj = json.loads(cleaned)
        except json.JSONDecodeError:
            return None
    return obj if isinstance(obj, dict) else None


def compute_weighted_overall(scores: dict[str, Any]) -> float:
    total = 0.0
    weight = 0.0
    for field, w in WEIGHTS.items():
        if scores.get(field) is not None:
            total += float(scores[field]) * w
            weight += w
    return round(total / weight, 1) if weight > 0 else 70.0


_ALIASES: dict[str, list[str]] = {
    "accuracy": ["accuracy", "precision", "factual"],
    "relevance": ["relevance", "pertinence"],
    "completeness": ["completeness", "thoroughness"],
    "tone": ["tone", "style"],
    "harm_risk": ["harm_risk", "harm", "risk", "safety"],
    "timing": ["timing", "opportunity"],
    "overall": ["overall", "global", "final", "aggregate"],
}


def parse_review_scores(raw_output: str | None) -> dict[str, Any]:
    """Parse reviewer scores; missing fields default to a neutral 70."""
    result: dict[str, Any] = {
        "accuracy": 70,
        "relevance": 70,
        "completeness": 70,
        "tone": 70,
        "harm_risk": 70,
        "timing": 70,
        "overall": 70,
        "reasoning": "",
        "parsed": False,
        "raw": raw_output,
    }
    obj = extract_json_object(raw_output)
    if not obj:
        return result
    result["parsed"] = True

    for field, aliases in _ALIASES.items():
        for alias in aliases:
            if obj.get(alias) is not None:
                try:
                    val = float(obj[alias])
                except (TypeError, ValueError):
                    continue
                result[field] = clamp(val, 0, 100)
                break

    if isinstance(obj.get("reasoning"), str):
        result["reasoning"] = obj["reasoning"][:500]

    if result["overall"] == 70 and result["parsed"]:
        result["overall"] = compute_weighted_overall(result)

    return result


def try_parse_intervention(text: str | None) -> dict[str, Any]:
    """Parse the primary/chairman intervention JSON (best-effort)."""
    obj = extract_json_object(text)
    if not obj:
        return {"parsed": False, "raw": text}
    return {
        "parsed": True,
        "should_intervene": obj.get("should_intervene"),
        "intervention_text": obj.get("intervention_text") or obj.get("intervention"),
        "category": obj.get("category"),
        "confidence": obj.get("confidence"),
        "reasoning": obj.get("reasoning"),
    }
