"""CDP Transfers API — programmatic fiat + crypto moves.

DISABLED. Flip WW_FEATURE_TRANSFERS=true to enable treasury operations
(cluster rebalancing, profit sweep to a holding wallet, etc.).
"""

from __future__ import annotations

from decimal import Decimal

from winny.common.features import features


def transfer_crypto(
    *,
    from_wallet: str,
    to_address: str,
    asset: str,
    amount: Decimal,
    network: str = "base",
) -> str:
    """Move `amount` of `asset` from one wallet to another. Returns tx hash."""
    features().require(
        "transfers", "set WW_FEATURE_TRANSFERS=true to enable"
    )
    raise NotImplementedError


def transfer_fiat(
    *,
    from_account_id: str,
    to_account_id: str,
    amount: Decimal,
    currency: str = "USD",
) -> str:
    features().require("transfers")
    raise NotImplementedError
