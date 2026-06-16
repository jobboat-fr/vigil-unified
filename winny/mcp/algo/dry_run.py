"""dry_run + get_dry_run_status — async backtest with pollable handle.

Per ADR-0005, the v1 "dry run" is an async-launched backtest that returns
a handle immediately. The caller polls `get_dry_run_status(handle_id)` to
discover state: RUNNING → COMPLETED (or FAILED).

This is the foundation for true live polling in a follow-up: replace the
"finite bars" input with a "bars provider" callable that yields fresh
bars on a schedule. Today, dry_run uses the same inline-bars input as
backtest — but executed asynchronously so the MCP call doesn't block.

State store: in-memory `_HANDLES: dict[str, _DryRunRecord]`. Process-local,
non-persistent. Restart loses in-flight handles — acceptable for v1.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from winny.common.errors import WinnyValidationError
from winny.common.ids import new_decision_id
from winny.mcp.algo.tools import backtest


class DryRunStatus(StrEnum):
    """Status of a dry-run task."""

    PENDING = "PENDING"  # accepted, not yet started
    RUNNING = "RUNNING"  # async task in flight
    COMPLETED = "COMPLETED"  # task finished cleanly; result available
    FAILED = "FAILED"  # task raised; error message available


# ===================================================================
# In-memory record + global store
# ===================================================================


@dataclass(slots=True)
class _DryRunRecord:
    """Internal state for one dry-run task."""

    handle_id: str
    status: DryRunStatus
    submitted_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict[str, Any] | None = None  # BacktestReport dict on success
    error: str | None = None  # exception message on failure
    task: asyncio.Task[Any] | None = field(default=None, repr=False)


# Process-local store. Not persistent across restarts; that's fine for v1.
_HANDLES: dict[str, _DryRunRecord] = {}
_HANDLES_LOCK = asyncio.Lock()


def _new_handle_id() -> str:
    """Mint a unique dry-run handle ID. Prefixed `dry_` for grep-ability."""
    return f"dry_{new_decision_id().removeprefix('dec_')}"


# ===================================================================
# dry_run tool — launch + return handle
# ===================================================================


async def dry_run(
    strategy: str,
    symbols: list[str],
    bars: dict[str, list[dict[str, Any]]],
    *,
    start: str | None = None,
    end: str | None = None,
    timeframe: str = "1d",
    initial_capital: str = "100000",
    quote_currency: str = "USD",
    seed: int = 42,
    wall_time_budget_seconds: float | None = None,
    market_specs_overrides: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Kick off an async backtest and return a handle immediately.

    The caller polls `get_dry_run_status(handle_id)` to discover completion.
    Same input shape as `backtest()` — see that tool for parameter semantics.

    Returns:
        {handle_id, status, submitted_at} — minimal envelope.

    The handle stays in the process-local store until the caller explicitly
    drops it (drop_handle is internal; future cleanup is a TODO).
    """
    handle_id = _new_handle_id()
    record = _DryRunRecord(
        handle_id=handle_id,
        status=DryRunStatus.PENDING,
        submitted_at=datetime.now(UTC),
    )

    async with _HANDLES_LOCK:
        _HANDLES[handle_id] = record

    # Spawn the worker. We use create_task so the handle is returned
    # immediately and the backtest runs in the background.
    record.task = asyncio.create_task(
        _run_dry_run(
            handle_id=handle_id,
            strategy=strategy,
            symbols=symbols,
            bars=bars,
            start=start,
            end=end,
            timeframe=timeframe,
            initial_capital=initial_capital,
            quote_currency=quote_currency,
            seed=seed,
            wall_time_budget_seconds=wall_time_budget_seconds,
            market_specs_overrides=market_specs_overrides,
        )
    )

    return {
        "handle_id": handle_id,
        "status": record.status.value,
        "submitted_at": record.submitted_at.isoformat(),
    }


async def _run_dry_run(
    *,
    handle_id: str,
    strategy: str,
    symbols: list[str],
    bars: dict[str, list[dict[str, Any]]],
    start: str | None,
    end: str | None,
    timeframe: str,
    initial_capital: str,
    quote_currency: str,
    seed: int,
    wall_time_budget_seconds: float | None,
    market_specs_overrides: dict[str, dict[str, Any]] | None,
) -> None:
    """Background worker that runs a backtest and posts the result to the handle."""
    record = _HANDLES[handle_id]
    record.status = DryRunStatus.RUNNING
    record.started_at = datetime.now(UTC)

    try:
        result = await backtest(
            strategy=strategy,
            symbols=symbols,
            bars=bars,
            start=start,
            end=end,
            timeframe=timeframe,
            initial_capital=initial_capital,
            quote_currency=quote_currency,
            seed=seed,
            wall_time_budget_seconds=wall_time_budget_seconds,
            market_specs_overrides=market_specs_overrides,
        )
        record.result = result
        record.status = DryRunStatus.COMPLETED
    except Exception as e:
        # Broad on purpose: any failure in the background task ends as FAILED;
        # caller gets the error via get_dry_run_status.
        record.error = f"{type(e).__name__}: {e}"
        record.status = DryRunStatus.FAILED
    finally:
        record.completed_at = datetime.now(UTC)


# ===================================================================
# get_dry_run_status — poll by handle
# ===================================================================


async def get_dry_run_status(handle_id: str) -> dict[str, Any]:
    """Look up a dry-run handle and return its current state.

    Args:
        handle_id: a handle previously returned by `dry_run`.

    Returns:
        Dict containing the handle's status and (if completed) the full
        BacktestReport dict, or (if failed) the error message.

    Raises:
        WinnyValidationError if the handle is unknown.
    """
    record = _HANDLES.get(handle_id)
    if record is None:
        raise WinnyValidationError(f"unknown dry-run handle: {handle_id!r}")

    out: dict[str, Any] = {
        "handle_id": record.handle_id,
        "status": record.status.value,
        "submitted_at": record.submitted_at.isoformat(),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": record.completed_at.isoformat() if record.completed_at else None,
    }
    if record.status is DryRunStatus.COMPLETED:
        out["result"] = record.result
    elif record.status is DryRunStatus.FAILED:
        out["error"] = record.error
    return out


# ===================================================================
# Test helpers — kept internal but importable for tests
# ===================================================================


def _sync_clear_handles_for_tests() -> None:
    """Drop all in-memory handles. Sync — safe to call from non-async fixtures.

    Between tests no async work is happening, so we don't need the asyncio
    lock. Task cancellation is fire-and-forget; the event loop tears down
    the task on its next run.
    """
    for record in _HANDLES.values():
        if record.task is not None and not record.task.done():
            record.task.cancel()
    _HANDLES.clear()


async def _clear_handles_for_tests() -> None:
    """Async variant for tests that want to await the cleanup explicitly."""
    async with _HANDLES_LOCK:
        _sync_clear_handles_for_tests()


async def _wait_for_handle(handle_id: str, timeout: float = 10.0) -> None:
    """Block until the named handle reaches a terminal state. Test helper."""
    record = _HANDLES.get(handle_id)
    if record is None:
        raise WinnyValidationError(f"unknown handle: {handle_id!r}")
    if record.task is None:
        return
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(record.task, timeout=timeout)
