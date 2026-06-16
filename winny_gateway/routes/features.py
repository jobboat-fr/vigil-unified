"""GET /api/v1/features — surface the feature switchboard to the frontend.

The dashboard reads this once at boot to decide which panels/buttons to
render. No auth required: flag-presence isn't sensitive, the dangerous
thing is the env vars backing them.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from winny_gateway.logging import get_logger
from winny.common.features import features

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/features", tags=["features"])


@router.get("")
async def get_features() -> dict[str, Any]:
    """Return the live feature flag map."""
    return {"ok": True, "data": features().as_dict()}
