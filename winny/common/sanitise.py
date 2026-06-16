"""Input sanitisation & prompt-injection detection — SECURITY HARDENING.

Centralised guards used by the gateway and internal tools to:
  1. Strip control characters and null bytes from all user text.
  2. Detect LLM/prompt-injection patterns before they reach any model or tool.
  3. Validate string identifiers (order IDs, symbols, broker names) against
     strict allow-lists and regex patterns.
  4. Cap input lengths to prevent denial-of-service via oversized payloads.

Usage:
    from winny.common.sanitise import sanitise_text, check_prompt_injection

    clean = sanitise_text(user_input, max_length=2000)
    if (threat := check_prompt_injection(clean)) is not None:
        raise ValueError(f"Prompt injection detected: {threat}")
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_CHAT_LENGTH = 2000
MAX_FIELD_LENGTH = 256
MAX_API_KEY_LENGTH = 512

# Characters that should never appear in user-facing text.
# Includes null, BEL, backspace, and other C0 controls EXCEPT \n \r \t.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# ---------------------------------------------------------------------------
# Prompt injection patterns
# ---------------------------------------------------------------------------
# These detect common LLM jailbreak / injection techniques.  The list is
# intentionally broad; false positives are surfaced as a named threat so the
# caller can decide whether to block or flag.

@dataclass(frozen=True, slots=True)
class PromptThreat:
    """A detected prompt-injection signal."""
    pattern_name: str
    matched_text: str

_PROMPT_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Direct instruction override
    ("instruction_override", re.compile(
        r"\b(ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions?|rules?|prompts?|commands?|guidelines?))\b",
        re.I,
    )),
    ("new_instructions", re.compile(
        r"\b(your\s+new\s+(instructions?|rules?|task|goal|objective)|from\s+now\s+on\s+(you\s+are|act\s+as|pretend|behave))\b",
        re.I,
    )),
    # System prompt extraction
    ("system_prompt_leak", re.compile(
        r"\b(show|reveal|display|print|output|repeat|echo)\s+(your\s+)?(system\s*prompt|initial\s*prompt|instructions?|rules?|hidden\s*prompt)\b",
        re.I,
    )),
    # Role hijacking
    ("role_hijack", re.compile(
        r"\b(you\s+are\s+now|act\s+as\s+if|pretend\s+(to\s+be|you\s+are)|role\s*play\s+as|simulate\s+being)\b",
        re.I,
    )),
    # Encoded / obfuscated injections
    ("base64_payload", re.compile(
        r"\b(decode|base64|eval|exec)\s*\(", re.I,
    )),
    # Delimiter injection (trying to break out of a prompt template)
    ("delimiter_injection", re.compile(
        r"(```\s*(system|assistant|user)\b|<\|im_start\|>|<\|im_end\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>)",
        re.I,
    )),
    # SQL injection fragments in text fields (defence-in-depth)
    ("sql_fragment", re.compile(
        r"(\b(UNION\s+SELECT|DROP\s+TABLE|INSERT\s+INTO|DELETE\s+FROM|UPDATE\s+\w+\s+SET|ALTER\s+TABLE)\b"
        r"|;\s*--"
        r"|'\s*OR\s+'1'\s*=\s*'1"
        r"|'\s*OR\s+1\s*=\s*1"
        r"|'\s*;\s*DROP\b)",
        re.I,
    )),
    # Command injection
    ("command_injection", re.compile(
        r"(\$\(|`[^`]+`\s*;|\b(os\.system|subprocess|eval|exec|__import__)\s*\()",
        re.I,
    )),
    # Markdown/HTML injection that could affect rendering
    ("html_injection", re.compile(
        r"(<\s*script\b|<\s*iframe\b|<\s*object\b|<\s*embed\b|javascript\s*:|on(error|load|click)\s*=)",
        re.I,
    )),
    # Excessive repetition (token-flooding DoS)
    ("token_flooding", re.compile(
        r"(.)\1{50,}",
    )),
]


def sanitise_text(text: str, *, max_length: int = MAX_CHAT_LENGTH) -> str:
    """Clean user text: strip control chars, trim whitespace, cap length.

    This is a *normalisation* step — it does NOT reject malicious input,
    only neutralises it.  Call ``check_prompt_injection`` afterwards for
    detection.
    """
    # 1. Remove null bytes and dangerous control characters
    cleaned = _CONTROL_RE.sub("", text)
    # 2. Normalise whitespace (collapse runs, strip outer)
    cleaned = " ".join(cleaned.split())
    # 3. Cap length
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]
    return cleaned


def check_prompt_injection(text: str) -> PromptThreat | None:
    """Scan text for known prompt-injection patterns.

    Returns the first detected threat, or None if clean.
    """
    for name, pattern in _PROMPT_INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return PromptThreat(pattern_name=name, matched_text=m.group(0))
    return None


def check_all_prompt_injections(text: str) -> list[PromptThreat]:
    """Return *all* detected threats (for logging / audit)."""
    threats: list[PromptThreat] = []
    for name, pattern in _PROMPT_INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            threats.append(PromptThreat(pattern_name=name, matched_text=m.group(0)))
    return threats


# ---------------------------------------------------------------------------
# ID / field validators
# ---------------------------------------------------------------------------

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")
_SYMBOL_RE = re.compile(r"^[A-Z]{1,2}:[A-Z0-9\-]+(@[a-z]+)?$")
_BROKER_IDS = frozenset({"binance", "kraken", "coinbase", "okx", "bybit", "gate"})


def validate_identifier(value: str, field_name: str = "id") -> str:
    """Ensure a string ID is safe for use as a key / path component."""
    if not _SAFE_ID_RE.match(value):
        raise ValueError(
            f"Invalid {field_name}: must be 1-128 alphanumeric/dash/underscore chars"
        )
    return value


def validate_symbol(value: str) -> str:
    """Validate a canonical WinnyWoo symbol string."""
    if not _SYMBOL_RE.match(value):
        raise ValueError(f"Invalid symbol format: {value!r}")
    return value


def validate_broker_id(value: str) -> str:
    """Validate broker ID against the known allow-list."""
    lower = value.lower()
    if lower not in _BROKER_IDS:
        raise ValueError(
            f"Unknown broker {value!r}. Allowed: {sorted(_BROKER_IDS)}"
        )
    return lower


def validate_api_key(value: str, field_name: str = "api_key") -> str:
    """Validate an API key / secret is within safe bounds."""
    if not value:
        return value
    if len(value) > MAX_API_KEY_LENGTH:
        raise ValueError(f"{field_name} exceeds maximum length ({MAX_API_KEY_LENGTH})")
    # API keys should be printable ASCII — reject control chars & null bytes
    if _CONTROL_RE.search(value):
        raise ValueError(f"{field_name} contains invalid control characters")
    return value


# ---------------------------------------------------------------------------
# SQL parameter helpers (defence-in-depth for DuckDB / SQLite)
# ---------------------------------------------------------------------------

def safe_int(value: object, *, min_val: int = 0, max_val: int = 100_000, name: str = "value") -> int:
    """Coerce to int with strict bounds — prevents injection via LIMIT/OFFSET."""
    if isinstance(value, int):
        n = value
    elif isinstance(value, str):
        try:
            n = int(value)
        except ValueError as e:
            raise ValueError(f"{name} must be an integer") from e
    else:
        raise ValueError(f"{name} must be an integer")
    if n < min_val or n > max_val:
        raise ValueError(f"{name} must be between {min_val} and {max_val}")
    return n
