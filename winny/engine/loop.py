"""Bar-driven engine loop — PR #11, §3.3.4.

Same code path for BACKTEST, DRY_RUN, and LIVE (deferred). Only DataProvider
and Brokerage swap. This module owns:
  - Per-bar iteration with lookahead-free data slicing
  - Strategy populate_*() orchestration
  - Signal extraction → sizing → intent construction → brokerage submission
  - Stoploss + minimal_roi enforcement (engine-level, not strategy)
  - Failure isolation (one symbol's exception does not halt the cycle)
  - Audit event emission on every state transition
  - Equity curve tracking + BacktestReport construction

Hard requirements (from architecture doc):
  R1: Strategies see only data with ts <= current_bar.ts (lookahead-free)
  R2: Every sizing decision passes through apply_nav_cap (§1.3 chokepoint)
  R3: Same seed + same data → bit-identical results (determinism)
  R4: Stop-loss + minimal_roi enforced by engine, not strategy
  R5: One symbol's exception MUST NOT halt the cycle (failure isolation)
  R6: Cycle budget (wall time) enforced; partial results allowed
  R7: Every state transition emits an AuditEvent
  R8: Backtest 50 symbols x 1y hourly bars in P95 < 8s
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any

import polars as pl

from winny.brokerage.paper import PaperBrokerage
from winny.common.audit import AuditStore, EventType
from winny.common.errors import WinnyError, WinnyValidationError
from winny.common.ids import (
    BrokerOrderId,
    Currency,
)
from winny.common.symbols import Symbol
from winny.common.types import (
    Bar,
    MarketSpec,
    Side,
)
from winny.engine.fees import DefaultFeeModel, FeeModel
from winny.engine.intent import DirectIntentHandler, IntentBuilder, IntentHandler
from winny.engine.results import (
    BacktestMetrics,
    BacktestReport,
    EquityPoint,
    TradeRecord,
)
from winny.engine.signals import Signal, SignalType, extract_signals, validate_signal_columns
from winny.engine.sizing import FixedFractionalSizing, SizingPolicy
from winny.engine.slippage import BpsSlippageModel, SlippageModel
from winny.engine.strategy import BarMeta, WinnyStrategy

logger = logging.getLogger(__name__)


# ===================================================================
# Engine mode
# ===================================================================


class EngineMode(StrEnum):
    """Operating mode for the engine loop."""

    BACKTEST = "BACKTEST"
    DRY_RUN = "DRY_RUN"
    LIVE = "LIVE"  # deferred to PR #13


# ===================================================================
# Engine configuration
# ===================================================================


@dataclass(frozen=True, slots=True)
class EngineConfig:
    """Immutable configuration for one engine run.

    All monetary defaults are conservative: 5 bps slippage, default fees,
    5% NAV per trade cap.
    """

    mode: EngineMode = EngineMode.BACKTEST
    initial_capital: Decimal = Decimal("100000")
    quote_currency: Currency = field(default_factory=lambda: Currency("USD"))
    fee_model: FeeModel = field(default_factory=DefaultFeeModel)
    slippage_model: SlippageModel = field(default_factory=BpsSlippageModel)
    sizing_policy: SizingPolicy = field(default_factory=FixedFractionalSizing)
    seed: int = 42
    max_open_trades: int = 10
    wall_time_budget_seconds: float | None = None  # None = no limit
    emit_audit_events: bool = True
    audit_store: AuditStore | None = None  # optional; if set, R7 events are emitted


# ===================================================================
# Audit helpers (R7)
# ===================================================================


def _emit(
    audit: AuditStore | None,
    event_type: EventType | str,
    payload: dict[str, Any] | None = None,
    *,
    decision_id: str | None = None,
) -> None:
    """Best-effort audit event emission. Never raises in backtest mode."""
    if audit is None:
        return
    try:
        audit.append(event_type, payload, decision_id=decision_id)
    except Exception:
        logger.debug("audit_emit_failed event_type=%s", event_type, exc_info=True)


# ===================================================================
# Internal state tracking
# ===================================================================


@dataclass(slots=True)
class _OpenPosition:
    """Mutable tracking of an open trade within the engine."""

    symbol: Symbol
    side: Side
    entry_price: Decimal
    qty: Decimal
    entry_ts: datetime
    entry_tag: str | None
    entry_order_id: BrokerOrderId
    stoploss_pct: Decimal  # current effective stoploss (negative)
    highest_price: Decimal  # for trailing stop tracking
    lowest_price: Decimal  # for short trailing stop
    bars_held: int = 0


# ===================================================================
# The engine loop
# ===================================================================


def run_backtest(
    strategy: WinnyStrategy,
    symbols: list[Symbol],
    bars_by_symbol: dict[Symbol, pl.DataFrame],
    market_specs: dict[Symbol, MarketSpec],
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    config: EngineConfig | None = None,
) -> BacktestReport:
    """Run a complete backtest over historical bar data.

    Parameters
    ----------
    strategy : The strategy instance to test.
    symbols : Universe of symbols to trade.
    bars_by_symbol : Pre-fetched OHLCV bars per symbol (ts, open, high, low, close, volume).
                     Each DataFrame MUST be sorted by ts ascending.
    market_specs : Per-symbol trading rules (tick size, lot size, fees).
    start : Inclusive start of backtest period. None = earliest available bar.
    end : Inclusive end of backtest period. None = latest available bar.
    config : Engine configuration. Defaults to conservative settings.

    Returns
    -------
    BacktestReport with trades, equity curve, and metrics.
    """
    cfg = config or EngineConfig()
    wall_start = time.perf_counter()

    # Initialize paper broker
    broker = PaperBrokerage(
        initial_cash={cfg.quote_currency: cfg.initial_capital},
        market_specs=market_specs,
        fee_model=cfg.fee_model,
        slippage_model=cfg.slippage_model,
        seed=cfg.seed,
    )

    # Fix #4: IntentBuilder is the sole OrderIntent constructor (nav-cap chokepoint)
    intent_builder = IntentBuilder(fee_model=cfg.fee_model)
    # Fix #5: IntentHandler abstracts broker dispatch (backtest vs live seam)
    intent_handler: IntentHandler = DirectIntentHandler(broker=broker)

    # Build the unified timeline: sorted unique timestamps across all symbols
    timeline = _build_timeline(bars_by_symbol, start, end)
    if not timeline:
        raise WinnyValidationError("no bars in the specified time range")

    # Pre-compute ts -> row index for each symbol (Fix #3: O(N) instead of O(N^2))
    ts_index_map: dict[Symbol, dict[datetime, int]] = {}
    for sym, df in bars_by_symbol.items():
        if df.is_empty():
            continue
        ts_list = df["ts"].to_list()
        ts_index_map[sym] = {t: i for i, t in enumerate(ts_list)}

    # State
    open_positions: dict[Symbol, _OpenPosition] = {}
    completed_trades: list[TradeRecord] = []
    equity_curve: list[EquityPoint] = []
    peak_nav = cfg.initial_capital
    bars_processed = 0
    errors: list[dict[str, Any]] = []
    last_close_cache: dict[Symbol, Decimal] = {}  # symbol -> most recent close price

    # R7: emit SERVICE_STARTED before any work
    _emit(
        cfg.audit_store,
        EventType.SERVICE_STARTED,
        {
            "mode": cfg.mode.value,
            "strategy_name": type(strategy).__name__,
            "symbols": [s.canonical() for s in symbols],
            "initial_capital": str(cfg.initial_capital),
            "quote_currency": str(cfg.quote_currency),
            "seed": cfg.seed,
            "config_hash": _config_hash(cfg, strategy),
        },
    )

    # Call bot_start
    strategy.bot_start()

    for ts in timeline:
        # Budget check (R6)
        if cfg.wall_time_budget_seconds is not None:
            elapsed = time.perf_counter() - wall_start
            if elapsed > cfg.wall_time_budget_seconds:
                logger.warning(
                    "engine_budget_exceeded elapsed_s=%s budget_s=%s bars_so_far=%s",
                    round(elapsed, 2),
                    cfg.wall_time_budget_seconds,
                    bars_processed,
                )
                break

        # Lifecycle hook
        strategy.bot_loop_start(ts)

        for symbol in symbols:
            try:
                _process_symbol_bar(
                    strategy=strategy,
                    symbol=symbol,
                    ts=ts,
                    bars_by_symbol=bars_by_symbol,
                    broker=broker,
                    cfg=cfg,
                    open_positions=open_positions,
                    completed_trades=completed_trades,
                    last_close_cache=last_close_cache,
                    ts_index_map=ts_index_map.get(symbol, {}),
                    intent_builder=intent_builder,
                    intent_handler=intent_handler,
                )
            except Exception as e:
                # R5: failure isolation — log and continue
                errors.append({"symbol": symbol.canonical(), "ts": str(ts), "error": str(e)})
                logger.error(
                    "engine_symbol_error symbol=%s ts=%s error=%s type=%s",
                    symbol.canonical(),
                    str(ts),
                    str(e),
                    type(e).__name__,
                )

        # Record equity point (use the cache for O(1) instead of re-scanning bars)
        nav = _compute_nav_from_cache(broker, last_close_cache, cfg.quote_currency)
        if nav > peak_nav:
            peak_nav = nav
        dd_pct = ((peak_nav - nav) / peak_nav * 100) if peak_nav > 0 else Decimal("0")
        cash = broker.get_balance().get(cfg.quote_currency, Decimal("0"))
        equity_curve.append(
            EquityPoint(
                ts=ts,
                nav=nav,
                cash=cash,
                positions_value=nav - cash,
                drawdown_pct=dd_pct,
            )
        )
        bars_processed += 1

    # Force-close open positions at backtest end
    last_ts = timeline[-1] if timeline else datetime.now(UTC)
    for symbol, pos in list(open_positions.items()):
        last_price = last_close_cache.get(symbol)
        if last_price is not None:
            trade = _close_position(pos, last_price, last_ts, "end_of_backtest")
            completed_trades.append(trade)
            # R7: force-close at end-of-backtest is a real position lifecycle
            # event — emit it for audit/replay so the chain is complete.
            _emit(
                cfg.audit_store,
                EventType.ORDER_FILLED,
                {
                    "symbol": symbol.canonical(),
                    "exit_reason": "end_of_backtest",
                    "exit_price": str(last_price),
                    "pnl": str(trade.pnl),
                    "entry_order_id": str(pos.entry_order_id),
                    "exit_order_id": None,
                },
            )
    open_at_end = len(open_positions)
    open_positions.clear()

    # Build metrics
    wall_time = time.perf_counter() - wall_start
    metrics = _compute_metrics(
        completed_trades, equity_curve, cfg.initial_capital, bars_processed, wall_time
    )
    symbols_traded = len({t.symbol for t in completed_trades})

    report = BacktestReport(
        strategy_name=type(strategy).__name__,
        timeframe=strategy.timeframe,
        start=timeline[0] if timeline else datetime.now(UTC),
        end=timeline[-1] if timeline else datetime.now(UTC),
        initial_capital=cfg.initial_capital,
        symbols=symbols,
        trades=completed_trades,
        equity_curve=equity_curve,
        metrics=metrics,
        open_trades_at_end=open_at_end,
        config_hash=_config_hash(cfg, strategy),
    )
    report.metrics.symbols_traded = symbols_traded

    if errors:
        logger.warning("engine_completed_with_errors error_count=%s", len(errors))

    # R7: emit SERVICE_STOPPED with summary so replay can detect clean completion
    _emit(
        cfg.audit_store,
        EventType.SERVICE_STOPPED,
        {
            "bars_processed": bars_processed,
            "trades": len(completed_trades),
            "final_nav": str(metrics.final_nav),
            "return_pct": str(metrics.return_pct),
            "errors": len(errors),
            "wall_time_seconds": round(wall_time, 3),
        },
    )

    return report


# ===================================================================
# Per-symbol bar processing
# ===================================================================


def _process_symbol_bar(
    *,
    strategy: WinnyStrategy,
    symbol: Symbol,
    ts: datetime,
    bars_by_symbol: dict[Symbol, pl.DataFrame],
    broker: PaperBrokerage,
    cfg: EngineConfig,
    open_positions: dict[Symbol, _OpenPosition],
    completed_trades: list[TradeRecord],
    last_close_cache: dict[Symbol, Decimal],
    ts_index_map: dict[datetime, int],
    intent_builder: IntentBuilder,
    intent_handler: IntentHandler,
) -> None:
    """Process one symbol at one timestamp. Core inner loop."""
    all_bars = bars_by_symbol.get(symbol)
    if all_bars is None or all_bars.is_empty():
        return

    # R1: Lookahead-free slicing — O(1) via pre-computed index map
    row_idx = ts_index_map.get(ts)
    if row_idx is None:
        return  # this symbol has no bar at this timestamp
    bar_count = row_idx + 1
    if bar_count < strategy.startup_candle_count:
        return  # not enough warm-up bars
    df = all_bars.head(bar_count)

    meta = BarMeta(symbol=symbol, ts=ts, timeframe=strategy.timeframe)

    # Get the current bar for broker tick
    current_row = df.tail(1).to_dicts()[0]
    current_bar = Bar(
        symbol=symbol,
        ts=ts,
        open=Decimal(str(current_row["open"])),
        high=Decimal(str(current_row["high"])),
        low=Decimal(str(current_row["low"])),
        close=Decimal(str(current_row["close"])),
        volume=Decimal(str(current_row["volume"])),
    )

    # Tick the broker (updates price, fires pending limits)
    broker.tick(symbol, current_bar)

    # Update last-close cache (used by NAV calculation)
    last_close_cache[symbol] = current_bar.close

    # R4: Check stoploss and minimal_roi for open positions BEFORE signals
    if symbol in open_positions:
        pos = open_positions[symbol]
        pos.bars_held += 1
        close_price = Decimal(str(current_row["close"]))
        high_price = Decimal(str(current_row["high"]))
        low_price = Decimal(str(current_row["low"]))

        # Update trailing tracking
        if high_price > pos.highest_price:
            pos.highest_price = high_price
        if low_price < pos.lowest_price:
            pos.lowest_price = low_price

        exit_reason = _check_engine_exits(pos, close_price, low_price, high_price, strategy)
        if exit_reason is not None:
            # Engine-enforced exit
            _execute_exit(
                pos=pos,
                exit_price=close_price,
                exit_ts=ts,
                exit_reason=exit_reason,
                cfg=cfg,
                open_positions=open_positions,
                completed_trades=completed_trades,
                intent_builder=intent_builder,
                intent_handler=intent_handler,
            )
            return  # skip signal processing for this symbol this bar

    # Run strategy populate methods
    df = strategy.populate_indicators(df, meta)
    df = strategy.populate_entry_trend(df, meta)
    df = strategy.populate_exit_trend(df, meta)

    # Validate signal columns
    validate_signal_columns(df)

    # Extract signals from last row
    signals = extract_signals(df, symbol, ts)

    # Process signals
    for signal in signals:
        _handle_signal(
            signal=signal,
            strategy=strategy,
            broker=broker,
            cfg=cfg,
            open_positions=open_positions,
            completed_trades=completed_trades,
            ts=ts,
            last_close_cache=last_close_cache,
            intent_builder=intent_builder,
            intent_handler=intent_handler,
        )


# ===================================================================
# Stoploss + Minimal ROI enforcement (R4)
# ===================================================================


def _check_engine_exits(
    pos: _OpenPosition,
    close_price: Decimal,
    low_price: Decimal,
    high_price: Decimal,
    strategy: WinnyStrategy,
) -> str | None:
    """Check if the engine should force-close this position.

    Returns the exit_reason string or None to keep the position open.
    Checks stoploss first (higher priority), then minimal_roi.
    """
    if pos.side is Side.BUY:
        # Long position: check if price dropped below stoploss
        pnl_pct = (close_price - pos.entry_price) / pos.entry_price
        low_pnl_pct = (low_price - pos.entry_price) / pos.entry_price

        # Stoploss hit? Check against intra-bar low
        if low_pnl_pct <= pos.stoploss_pct:
            return "stoploss"

        # Minimal ROI check (using close price)
        if strategy.minimal_roi is not None:
            minutes_held = pos.bars_held * _timeframe_minutes(strategy.timeframe)
            for roi_minutes, roi_threshold in sorted(strategy.minimal_roi.items(), reverse=True):
                if minutes_held >= roi_minutes and pnl_pct >= roi_threshold:
                    return "roi"
    else:
        # Short position (future support)
        pnl_pct = (pos.entry_price - close_price) / pos.entry_price
        high_pnl_pct = (pos.entry_price - high_price) / pos.entry_price

        if high_pnl_pct <= pos.stoploss_pct:
            return "stoploss"

        if strategy.minimal_roi is not None:
            minutes_held = pos.bars_held * _timeframe_minutes(strategy.timeframe)
            for roi_minutes, roi_threshold in sorted(strategy.minimal_roi.items(), reverse=True):
                if minutes_held >= roi_minutes and pnl_pct >= roi_threshold:
                    return "roi"

    return None


# ===================================================================
# Signal handling
# ===================================================================


def _handle_signal(
    *,
    signal: Signal,
    strategy: WinnyStrategy,
    broker: PaperBrokerage,
    cfg: EngineConfig,
    open_positions: dict[Symbol, _OpenPosition],
    completed_trades: list[TradeRecord],
    ts: datetime,
    last_close_cache: dict[Symbol, Decimal],
    intent_builder: IntentBuilder,
    intent_handler: IntentHandler,
) -> None:
    """Convert a signal into a broker action."""
    symbol = signal.symbol

    if signal.type is SignalType.ENTER_LONG:
        # Skip if already in a position for this symbol
        if symbol in open_positions:
            return
        # Skip if max open trades reached
        if len(open_positions) >= cfg.max_open_trades:
            return
        # Skip if strategy doesn't allow shorts for ENTER_SHORT
        _execute_entry(
            signal=signal,
            side=Side.BUY,
            strategy=strategy,
            broker=broker,
            cfg=cfg,
            open_positions=open_positions,
            ts=ts,
            last_close_cache=last_close_cache,
            intent_builder=intent_builder,
            intent_handler=intent_handler,
        )

    elif signal.type is SignalType.ENTER_SHORT:
        if not strategy.can_short:
            return  # reject per strategy config
        if symbol in open_positions:
            return
        if len(open_positions) >= cfg.max_open_trades:
            return
        _execute_entry(
            signal=signal,
            side=Side.SELL,
            strategy=strategy,
            broker=broker,
            cfg=cfg,
            open_positions=open_positions,
            ts=ts,
            last_close_cache=last_close_cache,
            intent_builder=intent_builder,
            intent_handler=intent_handler,
        )

    elif signal.type is SignalType.EXIT_LONG:
        if symbol not in open_positions:
            return
        pos = open_positions[symbol]
        if pos.side is not Side.BUY:
            return
        _execute_exit(
            pos=pos,
            exit_price=signal.bar_close,
            exit_ts=ts,
            exit_reason=f"signal:{signal.tag}" if signal.tag else "signal",
            cfg=cfg,
            open_positions=open_positions,
            completed_trades=completed_trades,
            intent_builder=intent_builder,
            intent_handler=intent_handler,
        )

    elif signal.type is SignalType.EXIT_SHORT:
        if symbol not in open_positions:
            return
        pos = open_positions[symbol]
        if pos.side is not Side.SELL:
            return
        _execute_exit(
            pos=pos,
            exit_price=signal.bar_close,
            exit_ts=ts,
            exit_reason=f"signal:{signal.tag}" if signal.tag else "signal",
            cfg=cfg,
            open_positions=open_positions,
            completed_trades=completed_trades,
            intent_builder=intent_builder,
            intent_handler=intent_handler,
        )


def _execute_entry(
    *,
    signal: Signal,
    side: Side,
    strategy: WinnyStrategy,
    broker: PaperBrokerage,
    cfg: EngineConfig,
    open_positions: dict[Symbol, _OpenPosition],
    ts: datetime,
    last_close_cache: dict[Symbol, Decimal],
    intent_builder: IntentBuilder,
    intent_handler: IntentHandler,
) -> None:
    """Construct an OrderIntent via IntentBuilder and dispatch via IntentHandler."""
    symbol = signal.symbol
    ref_price = signal.bar_close

    # Compute portfolio NAV for sizing -- mark-to-market using current prices
    nav = _compute_nav_from_cache(broker, last_close_cache, cfg.quote_currency)

    # Sizing (policy produces raw stake, IntentBuilder enforces nav-cap)
    stake = cfg.sizing_policy.stake_amount(symbol, side, ref_price, nav)

    # Let strategy override stake
    custom_stake = strategy.custom_stake_amount(
        symbol=symbol,
        current_ts=ts,
        current_rate=ref_price,
        proposed_stake=stake,
    )

    # Fix #4: IntentBuilder is the sole constructor -- nav-cap is structurally enforced
    intent = intent_builder.build_entry(
        symbol=symbol,
        side=side,
        ref_price=ref_price,
        stake=custom_stake,
        nav=nav,
        sizing_explanation=f"{type(cfg.sizing_policy).__name__}: stake={custom_stake}",
    )
    if intent is None:
        return  # capped to zero

    # Strategy confirmation hook (uses the qty from the built intent)
    if not strategy.confirm_trade_entry(
        symbol=symbol,
        side=side,
        qty=intent.qty,
        rate=ref_price,
        current_ts=ts,
        enter_tag=signal.tag,
    ):
        return

    # Fix #5: IntentHandler dispatches (direct in backtest, approval-gated in live)
    try:
        oid = intent_handler.handle(intent)
        if oid is None:
            return
        # Track open position
        open_positions[symbol] = _OpenPosition(
            symbol=symbol,
            side=side,
            entry_price=ref_price,
            qty=intent.qty,
            entry_ts=ts,
            entry_tag=signal.tag,
            entry_order_id=oid,
            stoploss_pct=strategy.stoploss,
            highest_price=ref_price,
            lowest_price=ref_price,
        )
        logger.info(
            "engine_entry symbol=%s side=%s qty=%s price=%s tag=%s",
            symbol.canonical(),
            side.value,
            str(intent.qty),
            str(ref_price),
            signal.tag,
        )
        # R7: audit trail
        _emit(
            cfg.audit_store,
            EventType.ORDER_SUBMITTED,
            {
                "symbol": symbol.canonical(),
                "side": side.value,
                "qty": str(intent.qty),
                "price": str(ref_price),
                "tag": signal.tag,
                "broker_order_id": str(oid),
            },
            decision_id=str(intent.decision_id),
        )
    except WinnyError as e:
        logger.warning(
            "engine_entry_rejected symbol=%s error=%s",
            symbol.canonical(),
            str(e),
        )
        _emit(
            cfg.audit_store,
            EventType.ORDER_REJECTED,
            {"symbol": symbol.canonical(), "side": side.value, "error": str(e)},
            decision_id=str(intent.decision_id),
        )


def _execute_exit(
    *,
    pos: _OpenPosition,
    exit_price: Decimal,
    exit_ts: datetime,
    exit_reason: str,
    cfg: EngineConfig,
    open_positions: dict[Symbol, _OpenPosition],
    completed_trades: list[TradeRecord],
    intent_builder: IntentBuilder,
    intent_handler: IntentHandler,
) -> None:
    """Build exit OrderIntent via IntentBuilder and dispatch via IntentHandler."""
    # For exits, the side is opposite to the position side
    exit_side = Side.SELL if pos.side is Side.BUY else Side.BUY

    # Fix #4: IntentBuilder is the sole constructor
    intent = intent_builder.build_exit(
        symbol=pos.symbol,
        exit_side=exit_side,
        qty=pos.qty,
        exit_price=exit_price,
        exit_reason=exit_reason,
    )

    # Fix #5: IntentHandler dispatches
    try:
        oid = intent_handler.handle(intent)
    except WinnyError as e:
        logger.warning("engine_exit_failed symbol=%s error=%s", pos.symbol.canonical(), str(e))
        oid = None

    # Compute PnL
    if pos.side is Side.BUY:
        pnl = (exit_price - pos.entry_price) * pos.qty - intent.estimated_fees
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
    else:
        pnl = (pos.entry_price - exit_price) * pos.qty - intent.estimated_fees
        pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

    duration = exit_ts - pos.entry_ts if exit_ts and pos.entry_ts else None

    completed_trades.append(
        TradeRecord(
            symbol=pos.symbol,
            side=pos.side,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            qty=pos.qty,
            entry_ts=pos.entry_ts,
            exit_ts=exit_ts,
            entry_tag=pos.entry_tag,
            exit_reason=exit_reason,
            pnl=pnl.quantize(Decimal("0.0001")),
            pnl_pct=pnl_pct.quantize(Decimal("0.01")),
            fees_paid=intent.estimated_fees,
            duration=duration,
            entry_order_id=pos.entry_order_id,
            exit_order_id=oid,
        )
    )

    # Remove from open positions
    del open_positions[pos.symbol]

    logger.info(
        "engine_exit symbol=%s reason=%s pnl=%s",
        pos.symbol.canonical(),
        exit_reason,
        str(pnl.quantize(Decimal("0.01"))),
    )
    # R7: audit trail
    _emit(
        cfg.audit_store,
        EventType.ORDER_FILLED,
        {
            "symbol": pos.symbol.canonical(),
            "exit_reason": exit_reason,
            "exit_price": str(exit_price),
            "pnl": str(pnl.quantize(Decimal("0.01"))),
            "exit_order_id": str(oid),
        },
        decision_id=str(intent.decision_id),
    )


# ===================================================================
# Helpers
# ===================================================================


def _build_timeline(
    bars_by_symbol: dict[Symbol, pl.DataFrame],
    start: datetime | None,
    end: datetime | None,
) -> list[datetime]:
    """Build a sorted list of unique bar timestamps across all symbols."""
    all_ts: set[datetime] = set()
    for df in bars_by_symbol.values():
        if df.is_empty():
            continue
        ts_col = df["ts"].to_list()
        all_ts.update(ts_col)

    if start:
        all_ts = {t for t in all_ts if t >= start}
    if end:
        all_ts = {t for t in all_ts if t <= end}

    return sorted(all_ts)


def _compute_nav_from_cache(
    broker: PaperBrokerage,
    last_close_cache: dict[Symbol, Decimal],
    quote_ccy: Currency,
) -> Decimal:
    """Compute mark-to-market NAV using the per-bar last-close cache.

    This is the correct NAV: cash + sum(position.qty * current_market_price).
    Using avg_entry_price here would under/overstate NAV and break the 5% cap.
    """
    cash = broker.get_balance().get(quote_ccy, Decimal("0"))
    positions_value = Decimal("0")
    for pos in broker.get_positions():
        price = last_close_cache.get(pos.symbol, pos.avg_entry_price)
        positions_value += pos.qty * price
    return cash + positions_value


def _close_position(
    pos: _OpenPosition, exit_price: Decimal, exit_ts: datetime, exit_reason: str
) -> TradeRecord:
    """Create a TradeRecord for a force-closed position (no broker interaction)."""
    if pos.side is Side.BUY:
        pnl = (exit_price - pos.entry_price) * pos.qty
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
    else:
        pnl = (pos.entry_price - exit_price) * pos.qty
        pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100

    return TradeRecord(
        symbol=pos.symbol,
        side=pos.side,
        entry_price=pos.entry_price,
        exit_price=exit_price,
        qty=pos.qty,
        entry_ts=pos.entry_ts,
        exit_ts=exit_ts,
        entry_tag=pos.entry_tag,
        exit_reason=exit_reason,
        pnl=pnl.quantize(Decimal("0.0001")),
        pnl_pct=pnl_pct.quantize(Decimal("0.01")),
        fees_paid=Decimal("0"),
        duration=exit_ts - pos.entry_ts,
        entry_order_id=pos.entry_order_id,
        exit_order_id=None,
    )


def _timeframe_minutes(tf: str) -> int:
    """Convert timeframe string to minutes."""
    mapping = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "2h": 120,
        "4h": 240,
        "1d": 1440,
        "1w": 10080,
    }
    return mapping.get(tf, 60)


def _compute_metrics(
    trades: list[TradeRecord],
    equity_curve: list[EquityPoint],
    initial_capital: Decimal,
    bars_processed: int,
    wall_time: float,
) -> BacktestMetrics:
    """Compute aggregate performance metrics from completed trades."""
    metrics = BacktestMetrics()
    metrics.initial_nav = initial_capital
    metrics.bars_processed = bars_processed
    metrics.wall_time_seconds = wall_time

    if not trades:
        metrics.final_nav = initial_capital
        return metrics

    metrics.total_trades = len(trades)
    winners = [t for t in trades if t.pnl > 0]
    losers = [t for t in trades if t.pnl < 0]
    metrics.winning_trades = len(winners)
    metrics.losing_trades = len(losers)
    metrics.win_rate = (
        Decimal(len(winners)) / Decimal(len(trades)) * 100 if trades else Decimal("0")
    )

    total_pnl = sum((t.pnl for t in trades), Decimal("0"))
    total_fees = sum((t.fees_paid for t in trades), Decimal("0"))
    metrics.total_pnl = total_pnl
    metrics.total_fees = total_fees
    metrics.avg_profit_pct = (
        sum((t.pnl_pct for t in trades), Decimal("0")) / Decimal(len(trades))
        if trades
        else Decimal("0")
    )

    # Final NAV from equity curve
    if equity_curve:
        metrics.final_nav = equity_curve[-1].nav
        metrics.max_drawdown_pct = max(
            (ep.drawdown_pct for ep in equity_curve), default=Decimal("0")
        )
    else:
        metrics.final_nav = initial_capital + total_pnl

    metrics.return_pct = (
        (metrics.final_nav - initial_capital) / initial_capital * 100
        if initial_capital > 0
        else Decimal("0")
    )

    # Profit factor
    gross_profit = sum((t.pnl for t in winners), Decimal("0"))
    gross_loss = abs(sum((t.pnl for t in losers), Decimal("0")))
    if gross_loss > 0:
        metrics.profit_factor = (gross_profit / gross_loss).quantize(Decimal("0.01"))

    # Average trade duration
    durations = [t.duration for t in trades if t.duration is not None]
    if durations:
        total_secs = sum(d.total_seconds() for d in durations)
        metrics.avg_trade_duration = timedelta(seconds=total_secs / len(durations))

    # Sharpe ratio (annualised, from per-bar equity returns)
    if len(equity_curve) >= 2:
        returns: list[Decimal] = []
        for i in range(1, len(equity_curve)):
            prev_nav = equity_curve[i - 1].nav
            if prev_nav > 0:
                returns.append((equity_curve[i].nav - prev_nav) / prev_nav)
        if len(returns) >= 2:
            n = Decimal(len(returns))
            mean_ret = sum(returns, Decimal("0")) / n
            var = sum((r - mean_ret) ** 2 for r in returns) / (n - 1)
            # Decimal doesn't have sqrt — use float then convert back
            std_ret = Decimal(str(float(var) ** 0.5))
            if std_ret > 0:
                # Annualise assuming hourly bars (~8760 bars/year)
                ann_factor = Decimal(str(8760**0.5))
                metrics.sharpe_ratio = (mean_ret / std_ret * ann_factor).quantize(Decimal("0.01"))

    return metrics


def _config_hash(cfg: EngineConfig, strategy: WinnyStrategy) -> str:
    """Produce a deterministic hash of engine + strategy config for reproducibility (R3)."""
    raw = json.dumps(
        {
            "mode": cfg.mode.value,
            "initial_capital": str(cfg.initial_capital),
            "seed": cfg.seed,
            "max_open_trades": cfg.max_open_trades,
            "strategy": type(strategy).__name__,
            "timeframe": strategy.timeframe,
            "startup_candle_count": strategy.startup_candle_count,
            "stoploss": str(strategy.stoploss),
            "can_short": strategy.can_short,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()
