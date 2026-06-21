"""Ops Team — the agentic-company engine (P0).

Departments are on-demand agent units with an effectiveness contract: a job, a
deterministic acceptance check, and a per-run budget. P0 ships one reference
department (Support / inbox triage) implemented in-gateway so the whole loop —
dispatch → work → artifact → acceptance → health — is provable without the OVH
round-trip. Later phases dispatch to Hermes profiles via the ops proxy.
"""
from winny_gateway.ops.engine import (
    DEPARTMENTS,
    compute_health,
    department_spec,
    run_job,
)

__all__ = ["DEPARTMENTS", "compute_health", "department_spec", "run_job"]
