"""Typed exception hierarchy for Winny.

Per SPECS.md §15.10: all errors are typed exceptions from this module.
`raise Exception(...)` is forbidden in code review.

Each subclass corresponds to a fault domain so callers can react meaningfully.
"""

from __future__ import annotations


class WinnyError(Exception):
    """Root of the Winny exception hierarchy.

    Catch this in cross-cutting handlers (CLI top-level, MCP server boundaries)
    but never inside business logic — always catch the specific subclass.
    """


# ---------- audit log ----------


class AuditError(WinnyError):
    """Base for audit-log faults. See §7.4."""


class AuditDatabaseError(AuditError):
    """Underlying SQLite layer failed (lock, disk full, schema mismatch)."""


class AuditChainBrokenError(AuditError):
    """Hash chain verification failed at a specific seq_no.

    This is a tamper / corruption signal. Per §9.1, the service MUST refuse
    to start until an operator restores from a known-good anchor.
    """

    def __init__(self, seq_no: int, reason: str) -> None:
        self.seq_no = seq_no
        self.reason = reason
        super().__init__(f"audit chain broken at seq_no={seq_no}: {reason}")


class AuditEmptyError(AuditError):
    """Operation requires events but the log has none (e.g. anchor on empty DB)."""


# ---------- approval (placeholders, fleshed out in PR #4) ----------


class ApprovalError(WinnyError):
    """Base for approval-gate faults. See §3.4."""


class GrantMalformedError(ApprovalError):
    """The grant token is structurally invalid (wrong shape, undecodable, etc.)."""


class GrantSignatureInvalidError(ApprovalError):
    """The Ed25519 signature failed verification — token may be forged or corrupted."""


class GrantExpiredError(ApprovalError):
    """The grant's expires_at is in the past."""


class GrantClockSkewError(ApprovalError):
    """The grant's issued_at is too far in the future. Per §9.1 we reject > 30s skew."""


class GrantIntentMismatchError(ApprovalError):
    """The grant's order_intent_hash does not match the intent being submitted."""


class GrantMismatchError(ApprovalError):
    """Internal field (approval_id) does not match the wrapper."""


class GrantReplayError(ApprovalError):
    """The grant has already been consumed. Replay attack or double-submit."""


# ---------- data layer (placeholders, fleshed out in PR #5) ----------


class DataError(WinnyError):
    """Base for data-layer faults."""


class ProviderUnavailableError(DataError):
    """A DataProvider cannot serve a request right now."""


# ---------- brokerage (PR #10) ----------


class BrokerageError(WinnyError):
    """Base for brokerage faults. See §3.3.5."""


class InsufficientBalanceError(BrokerageError):
    """Not enough cash in the quote currency to cover the requested order."""


class InsufficientPositionError(BrokerageError):
    """Not enough position qty to cover the requested sell (no-short mode)."""


class UnknownSymbolError(BrokerageError):
    """No MarketSpec registered for the symbol on this brokerage."""


class UnknownOrderError(BrokerageError):
    """Broker has no record of the given broker_order_id."""


class UnsupportedOrderTypeError(BrokerageError):
    """The brokerage does not support this OrderType / parameter combination."""


# ---------- validation ----------


class WinnyValidationError(WinnyError):
    """Input failed validation. Used at MCP-tool boundaries."""
