"""Typed identifier wrappers and ULID factories.

Per SPECS.md §4.1, identifiers are typed wrappers, never raw strings. This
catches the entire class of "pass a Symbol where a DecisionId is expected"
bugs at type-check time.

ULIDs are chosen over UUIDs because they're sortable by creation time and
shorter (26 chars vs 36). Prefix tags make them grep-friendly in audit logs.
"""

from __future__ import annotations

from typing import NewType

from ulid import ULID

# ---------- typed identifiers ----------

DecisionId = NewType("DecisionId", str)
"""ULID-backed identifier for a Decision. Prefixed `dec_`."""

ApprovalId = NewType("ApprovalId", str)
"""ULID-backed identifier for an ApprovalRequest. Prefixed `apv_`."""

BrokerOrderId = NewType("BrokerOrderId", str)
"""Opaque broker-assigned order ID. Format depends on the broker."""

IntentId = NewType("IntentId", str)
"""ULID-backed identifier for an OrderIntent. Prefixed `int_`."""

Currency = NewType("Currency", str)
"""Quote/base currency code, e.g. 'USD', 'USDT', 'EUR'. Uppercase by convention.

ISO 4217 for fiat (USD, EUR, GBP, JPY, ...). For crypto we use the venue's
symbol (USDT, USDC, BTC, ETH, ...). The brokerage layer is the source of
truth — we don't enforce a registry, just consistency within a deployment.
"""


# ---------- factories ----------


def new_decision_id() -> DecisionId:
    """Create a fresh DecisionId. Sortable, unique, prefixed."""
    return DecisionId(f"dec_{ULID()!s}")


def new_approval_id() -> ApprovalId:
    """Create a fresh ApprovalId."""
    return ApprovalId(f"apv_{ULID()!s}")


def new_intent_id() -> IntentId:
    """Create a fresh IntentId."""
    return IntentId(f"int_{ULID()!s}")
