"""CDP Paymaster — gasless transactions for smart-wallet flows.

DISABLED. Flip WW_FEATURE_PAYMASTER=true once we have a smart wallet
flow that benefits from sponsored gas (e.g. user-facing in-app actions
in the WinnyWoo dashboard).
"""

from __future__ import annotations

from winny.common.features import features


def sponsor_user_op(*, wallet_id: str, user_op: dict[str, object]) -> str:
    """Have the Paymaster pay gas for the given user operation."""
    features().require(
        "paymaster", "set WW_FEATURE_PAYMASTER=true to enable"
    )
    raise NotImplementedError
