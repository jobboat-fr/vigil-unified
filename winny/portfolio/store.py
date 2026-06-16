"""PortfolioStore — WAL'd SQLite persistence for portfolio state.

Follows the same pattern as winny.common.audit.AuditStore:
  - WAL journal mode for concurrent readers
  - synchronous=FULL for crash safety
  - Single in-process writer lock (threading.Lock)
  - busy_timeout=5s for inter-process contention

The store tracks three tables:
  - balances: cash per currency
  - positions: open positions per symbol (signed qty)
  - open_orders: orders submitted but not yet filled/cancelled

Read API is used by PR #15 tools. Write API is defined here but wired by PR #16.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from winny.common.ids import BrokerOrderId, Currency, IntentId
from winny.common.symbols import Symbol
from winny.common.types import OrderStatus, OrderType, Side

# ---------- schema ----------

_SCHEMA_BALANCES = """
CREATE TABLE IF NOT EXISTS balances (
    currency    TEXT PRIMARY KEY,
    amount      TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

_SCHEMA_POSITIONS = """
CREATE TABLE IF NOT EXISTS positions (
    symbol          TEXT PRIMARY KEY,
    qty             TEXT NOT NULL,
    avg_entry_price TEXT NOT NULL,
    opened_at       TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
"""

_SCHEMA_OPEN_ORDERS = """
CREATE TABLE IF NOT EXISTS open_orders (
    broker_order_id TEXT PRIMARY KEY,
    intent_id       TEXT NOT NULL,
    decision_id     TEXT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    qty             TEXT NOT NULL,
    order_type      TEXT NOT NULL,
    limit_price     TEXT,
    stop_price      TEXT,
    status          TEXT NOT NULL,
    submitted_at    TEXT NOT NULL,
    broker          TEXT NOT NULL DEFAULT 'paper'
);
"""

_IDX_POSITIONS_UPDATED = (
    "CREATE INDEX IF NOT EXISTS idx_positions_updated ON positions(updated_at);"
)
_IDX_ORDERS_SYMBOL = (
    "CREATE INDEX IF NOT EXISTS idx_orders_symbol ON open_orders(symbol);"
)
_IDX_ORDERS_STATUS = (
    "CREATE INDEX IF NOT EXISTS idx_orders_status ON open_orders(status);"
)


# ---------- value objects for rows ----------


class StoredPosition:
    """Row from the positions table."""

    __slots__ = ("avg_entry_price", "opened_at", "qty", "symbol", "updated_at")

    def __init__(
        self,
        symbol: str,
        qty: Decimal,
        avg_entry_price: Decimal,
        opened_at: str,
        updated_at: str,
    ) -> None:
        self.symbol = symbol
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.opened_at = opened_at
        self.updated_at = updated_at


class StoredOrder:
    """Row from the open_orders table."""

    __slots__ = (
        "broker",
        "broker_order_id",
        "decision_id",
        "intent_id",
        "limit_price",
        "order_type",
        "qty",
        "side",
        "status",
        "stop_price",
        "submitted_at",
        "symbol",
    )

    def __init__(
        self,
        broker_order_id: str,
        intent_id: str,
        decision_id: str | None,
        symbol: str,
        side: str,
        qty: Decimal,
        order_type: str,
        limit_price: Decimal | None,
        stop_price: Decimal | None,
        status: str,
        submitted_at: str,
        broker: str,
    ) -> None:
        self.broker_order_id = broker_order_id
        self.intent_id = intent_id
        self.decision_id = decision_id
        self.symbol = symbol
        self.side = side
        self.qty = qty
        self.order_type = order_type
        self.limit_price = limit_price
        self.stop_price = stop_price
        self.status = status
        self.submitted_at = submitted_at
        self.broker = broker


# ---------- helpers ----------


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _default_db_path() -> Path:
    """~/.winny/portfolio.db, overridable via WINNY_PORTFOLIO_PATH env var."""
    import os

    env_path = os.environ.get("WINNY_PORTFOLIO_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".winny" / "portfolio.db"


# ---------- store ----------


class PortfolioStoreError(Exception):
    """Raised on database errors within PortfolioStore."""


class PortfolioStore:
    """Thread-safe, restart-safe portfolio state store.

    Open once per process. Connection lives for the process lifetime.
    """

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(
                str(self.db_path),
                isolation_level=None,
                check_same_thread=False,
                timeout=5.0,
            )
        except sqlite3.Error as exc:
            raise PortfolioStoreError(
                f"cannot open portfolio db at {self.db_path}: {exc}"
            ) from exc
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        try:
            cur = self._conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=FULL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute(_SCHEMA_BALANCES)
            cur.execute(_SCHEMA_POSITIONS)
            cur.execute(_SCHEMA_OPEN_ORDERS)
            cur.execute(_IDX_POSITIONS_UPDATED)
            cur.execute(_IDX_ORDERS_SYMBOL)
            cur.execute(_IDX_ORDERS_STATUS)
        except sqlite3.Error as exc:
            raise PortfolioStoreError(f"schema init failed: {exc}") from exc

    def close(self) -> None:
        with self._lock, contextlib.suppress(sqlite3.Error):
            self._conn.close()

    # ===================================================================
    # Balance reads
    # ===================================================================

    def get_balance(self, currency: Currency) -> Decimal:
        """Get balance for a currency. Returns Decimal('0') if not found."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT amount FROM balances WHERE currency = ?", (str(currency),)
            )
            row = cur.fetchone()
            return Decimal(row[0]) if row else Decimal("0")

    def get_all_balances(self) -> dict[Currency, Decimal]:
        """Get all balances as {currency: amount}."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT currency, amount FROM balances")
            return {
                Currency(row[0]): Decimal(row[1]) for row in cur.fetchall()
            }

    # ===================================================================
    # Balance writes
    # ===================================================================

    def set_balance(self, currency: Currency, amount: Decimal) -> None:
        """Set (upsert) balance for a currency."""
        now = _utcnow_iso()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO balances (currency, amount, updated_at) "
                    "VALUES (?, ?, ?) "
                    "ON CONFLICT(currency) DO UPDATE SET amount=excluded.amount, "
                    "updated_at=excluded.updated_at",
                    (str(currency), str(amount), now),
                )
            except sqlite3.Error as exc:
                raise PortfolioStoreError(f"set_balance failed: {exc}") from exc

    # ===================================================================
    # Position reads
    # ===================================================================

    def get_position(self, symbol: Symbol) -> StoredPosition | None:
        """Get position for a symbol, or None if no position."""
        canonical = symbol.canonical()
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT symbol, qty, avg_entry_price, opened_at, updated_at "
                "FROM positions WHERE symbol = ?",
                (canonical,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return StoredPosition(
                symbol=row[0],
                qty=Decimal(row[1]),
                avg_entry_price=Decimal(row[2]),
                opened_at=row[3],
                updated_at=row[4],
            )

    def get_all_positions(self) -> list[StoredPosition]:
        """Get all open positions."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT symbol, qty, avg_entry_price, opened_at, updated_at "
                "FROM positions ORDER BY symbol"
            )
            return [
                StoredPosition(
                    symbol=row[0],
                    qty=Decimal(row[1]),
                    avg_entry_price=Decimal(row[2]),
                    opened_at=row[3],
                    updated_at=row[4],
                )
                for row in cur.fetchall()
            ]

    # ===================================================================
    # Position writes
    # ===================================================================

    def upsert_position(
        self,
        symbol: Symbol,
        qty: Decimal,
        avg_entry_price: Decimal,
    ) -> None:
        """Insert or update a position."""
        canonical = symbol.canonical()
        now = _utcnow_iso()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO positions (symbol, qty, avg_entry_price, opened_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(symbol) DO UPDATE SET qty=excluded.qty, "
                    "avg_entry_price=excluded.avg_entry_price, updated_at=excluded.updated_at",
                    (canonical, str(qty), str(avg_entry_price), now, now),
                )
            except sqlite3.Error as exc:
                raise PortfolioStoreError(f"upsert_position failed: {exc}") from exc

    def delete_position(self, symbol: Symbol) -> None:
        """Remove a position (full close)."""
        canonical = symbol.canonical()
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM positions WHERE symbol = ?", (canonical,)
                )
            except sqlite3.Error as exc:
                raise PortfolioStoreError(f"delete_position failed: {exc}") from exc

    # ===================================================================
    # Open order reads
    # ===================================================================

    def get_open_order(self, broker_order_id: BrokerOrderId) -> StoredOrder | None:
        """Get a single open order by broker ID."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT broker_order_id, intent_id, decision_id, symbol, side, "
                "qty, order_type, limit_price, stop_price, status, submitted_at, broker "
                "FROM open_orders WHERE broker_order_id = ?",
                (str(broker_order_id),),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_order(row)

    def get_open_orders(
        self,
        *,
        broker: str | None = None,
        symbol: Symbol | None = None,
    ) -> list[StoredOrder]:
        """Get open orders, optionally filtered by broker and/or symbol."""
        with self._lock:
            cur = self._conn.cursor()
            query = (
                "SELECT broker_order_id, intent_id, decision_id, symbol, side, "
                "qty, order_type, limit_price, stop_price, status, submitted_at, broker "
                "FROM open_orders"
            )
            conditions: list[str] = []
            params: list[str] = []

            if broker is not None:
                conditions.append("broker = ?")
                params.append(broker)
            if symbol is not None:
                conditions.append("symbol = ?")
                params.append(symbol.canonical())

            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY submitted_at"

            cur.execute(query, params)
            return [self._row_to_order(row) for row in cur.fetchall()]

    # ===================================================================
    # Open order writes
    # ===================================================================

    def record_open_order(
        self,
        *,
        broker_order_id: BrokerOrderId,
        intent_id: IntentId,
        decision_id: str | None,
        symbol: Symbol,
        side: Side,
        qty: Decimal,
        order_type: OrderType,
        limit_price: Decimal | None = None,
        stop_price: Decimal | None = None,
        status: OrderStatus = OrderStatus.PENDING,
        broker: str = "paper",
    ) -> None:
        """Record a newly submitted order."""
        now = _utcnow_iso()
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO open_orders "
                    "(broker_order_id, intent_id, decision_id, symbol, side, qty, "
                    "order_type, limit_price, stop_price, status, submitted_at, broker) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(broker_order_id),
                        str(intent_id),
                        decision_id,
                        symbol.canonical(),
                        side.value,
                        str(qty),
                        order_type.value,
                        str(limit_price) if limit_price is not None else None,
                        str(stop_price) if stop_price is not None else None,
                        status.value,
                        now,
                        broker,
                    ),
                )
            except sqlite3.Error as exc:
                raise PortfolioStoreError(
                    f"record_open_order failed: {exc}"
                ) from exc

    def update_order_status(
        self,
        broker_order_id: BrokerOrderId,
        status: OrderStatus,
    ) -> None:
        """Update the status of an open order."""
        with self._lock:
            try:
                self._conn.execute(
                    "UPDATE open_orders SET status = ? WHERE broker_order_id = ?",
                    (status.value, str(broker_order_id)),
                )
            except sqlite3.Error as exc:
                raise PortfolioStoreError(
                    f"update_order_status failed: {exc}"
                ) from exc

    def remove_open_order(self, broker_order_id: BrokerOrderId) -> None:
        """Remove an order (filled, cancelled, or rejected)."""
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM open_orders WHERE broker_order_id = ?",
                    (str(broker_order_id),),
                )
            except sqlite3.Error as exc:
                raise PortfolioStoreError(
                    f"remove_open_order failed: {exc}"
                ) from exc

    # ===================================================================
    # Test helpers
    # ===================================================================

    def _clear_all(self) -> None:
        """Remove all data. FOR TESTING ONLY."""
        with self._lock:
            self._conn.execute("DELETE FROM open_orders")
            self._conn.execute("DELETE FROM positions")
            self._conn.execute("DELETE FROM balances")

    def _count_open_orders(self) -> int:
        """Count open orders. Used internally and in tests."""
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("SELECT COUNT(*) FROM open_orders")
            row = cur.fetchone()
            return int(row[0]) if row else 0

    # ===================================================================
    # Internal
    # ===================================================================

    @staticmethod
    def _row_to_order(row: tuple[str, ...]) -> StoredOrder:
        return StoredOrder(
            broker_order_id=row[0],
            intent_id=row[1],
            decision_id=row[2],
            symbol=row[3],
            side=row[4],
            qty=Decimal(row[5]),
            order_type=row[6],
            limit_price=Decimal(row[7]) if row[7] is not None else None,
            stop_price=Decimal(row[8]) if row[8] is not None else None,
            status=row[9],
            submitted_at=row[10],
            broker=row[11],
        )
