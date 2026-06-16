"""ClusterStore — WAL'd SQLite persistence for cluster definitions.

Follows the same pattern as PortfolioStore and ApprovalStore:
  - WAL journal mode for concurrent readers
  - synchronous=FULL for crash safety
  - Single in-process writer lock
  - busy_timeout=5s for inter-process contention

Two tables:
  - clusters:        immutable ClusterPolicy rows
  - cluster_positions: open positions per cluster (separate from global portfolio)

Read API is implemented now; mutation calls land alongside the cluster
router PR. ENABLED by WW_FEATURE_CLUSTERS.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from pathlib import Path
from typing import Any

from winny.clusters.policy import ClusterPolicy, RiskProfile
from winny.common.features import features

_DEFAULT_DB_PATH = Path.home() / ".winny" / "clusters.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS clusters (
    cluster_id        TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    nav_target        TEXT NOT NULL,
    nav_currency      TEXT NOT NULL,
    risk_profile      TEXT NOT NULL,
    max_position_pct  TEXT NOT NULL,
    strategy_filter   TEXT NOT NULL,        -- comma-separated tags
    wallet_provider   TEXT NOT NULL,
    wallet_address    TEXT NOT NULL,
    active            INTEGER NOT NULL,
    created_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clusters_active ON clusters(active);
"""


class ClusterStore:
    """SQLite-backed registry of cluster policies."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=FULL;")
        self._conn.execute("PRAGMA busy_timeout=5000;")
        for stmt in _SCHEMA.strip().split(";"):
            if stmt.strip():
                self._conn.execute(stmt)
        self._conn.commit()

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._conn.close()

    # ─── reads ────────────────────────────────────────────────────────────

    def list_active(self) -> list[ClusterPolicy]:
        features().require("clusters")
        cursor = self._conn.execute(
            "SELECT cluster_id, name, nav_target, nav_currency, risk_profile, "
            "max_position_pct, strategy_filter, wallet_provider, wallet_address, "
            "active, created_at FROM clusters WHERE active = 1 ORDER BY created_at"
        )
        return [self._row_to_policy(r) for r in cursor.fetchall()]

    def list_all(self) -> list[ClusterPolicy]:
        features().require("clusters")
        cursor = self._conn.execute(
            "SELECT cluster_id, name, nav_target, nav_currency, risk_profile, "
            "max_position_pct, strategy_filter, wallet_provider, wallet_address, "
            "active, created_at FROM clusters ORDER BY created_at"
        )
        return [self._row_to_policy(r) for r in cursor.fetchall()]

    def get(self, cluster_id: str) -> ClusterPolicy | None:
        features().require("clusters")
        cursor = self._conn.execute(
            "SELECT cluster_id, name, nav_target, nav_currency, risk_profile, "
            "max_position_pct, strategy_filter, wallet_provider, wallet_address, "
            "active, created_at FROM clusters WHERE cluster_id = ?",
            (cluster_id,),
        )
        row = cursor.fetchone()
        return self._row_to_policy(row) if row else None

    # ─── writes ───────────────────────────────────────────────────────────

    def create(self, policy: ClusterPolicy) -> None:
        features().require("clusters")
        with self._lock:
            self._conn.execute(
                "INSERT INTO clusters (cluster_id, name, nav_target, nav_currency, "
                "risk_profile, max_position_pct, strategy_filter, wallet_provider, "
                "wallet_address, active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    policy.cluster_id,
                    policy.name,
                    str(policy.nav_target),
                    policy.nav_currency,
                    policy.risk_profile.value,
                    str(policy.max_position_pct),
                    ",".join(policy.strategy_filter),
                    policy.wallet_provider,
                    policy.wallet_address,
                    1 if policy.active else 0,
                    policy.created_at,
                ),
            )
            self._conn.commit()

    def set_active(self, cluster_id: str, active: bool) -> None:
        features().require("clusters")
        with self._lock:
            self._conn.execute(
                "UPDATE clusters SET active = ? WHERE cluster_id = ?",
                (1 if active else 0, cluster_id),
            )
            self._conn.commit()

    # ─── helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _row_to_policy(row: tuple[Any, ...]) -> ClusterPolicy:
        from decimal import Decimal

        from winny.common.ids import Currency

        tags = tuple(t for t in (row[6] or "").split(",") if t)
        return ClusterPolicy(
            cluster_id=row[0],
            name=row[1],
            nav_target=Decimal(row[2]),
            nav_currency=Currency(row[3]),
            risk_profile=RiskProfile(row[4]),
            max_position_pct=Decimal(row[5]),
            strategy_filter=tags,
            wallet_provider=row[7],
            wallet_address=row[8],
            active=bool(row[9]),
            created_at=row[10],
        )
