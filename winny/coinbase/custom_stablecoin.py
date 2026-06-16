"""Custom Stablecoin on Base — disabled until product fit is justified.

DISABLED. Out of scope for the current solopreneur trading-desk product;
listed for completeness so the contract is explicit. Flip
WW_FEATURE_CUSTOM_STABLECOIN=true only after a use case demands it.
"""

from __future__ import annotations

from winny.common.features import features


def issue_token(*args: object, **kwargs: object) -> None:
    features().require(
        "custom_stablecoin",
        "set WW_FEATURE_CUSTOM_STABLECOIN=true to enable — typically not needed",
    )
    raise NotImplementedError
