"""CDP Deposit Destination — dedicated onchain address per user.

DISABLED. Flip WW_FEATURE_DEPOSIT_DESTINATION=true to enable the
onboarding flow where a user funds their WinnyWoo account by sending
crypto to their dedicated address; Coinbase auto-credits + fires a
webhook; the gateway updates the cluster NAV.
"""

from __future__ import annotations

from winny.common.features import features


def provision_address(*, user_id: str, network: str = "base") -> str:
    features().require(
        "deposit_destination",
        "set WW_FEATURE_DEPOSIT_DESTINATION=true to enable",
    )
    raise NotImplementedError
