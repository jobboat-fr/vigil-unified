"""VIGIL AI Council — multi-model fan-out + consensus + chairman synthesis.

Ported from VIGIL backendv2 (Node) into the vigil-unified Python backend.
Public API:
    from winny.council import AIWorkerCollective, TASK_MATRIX, worker_registry
"""

from winny.council.collective import AIWorkerCollective
from winny.council.registry import (
    REVIEWER_SYSTEM_PROMPT,
    ROLE_SYSTEM_PROMPTS,
    TASK_MATRIX,
    worker_registry,
)

__all__ = [
    "AIWorkerCollective",
    "TASK_MATRIX",
    "worker_registry",
    "ROLE_SYSTEM_PROMPTS",
    "REVIEWER_SYSTEM_PROMPT",
]
