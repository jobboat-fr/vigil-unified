"""Tiny per-process TTL cache.

Used by endpoints that hit an external exchange and don't need sub-second
freshness — broker snapshot, balance, positions. Cuts dashboard load from
10–25 s (cold CCXT round-trip) to <50 ms when there's a recent hit.

NOT a distributed cache. Each Railway replica has its own. Acceptable for
single-user mode; revisit when we go multi-replica.

Usage:
    from winny_gateway.cache import snapshot_cache

    cached = snapshot_cache.get(("snapshot", user_id, broker))
    if cached is not None:
        return cached

    fresh = build_snapshot(...)
    snapshot_cache.set(("snapshot", user_id, broker), fresh, ttl=30)
    return fresh
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Hashable


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    """Thread-safe TTL cache with stale-while-revalidate semantics.

    `get()` returns fresh hits and prunes expired.
    `get_stale_ok()` returns expired entries too — callers use this to
    paint *something* immediately and then refresh in the background.
    """

    def __init__(self, default_ttl: float = 30.0, max_entries: int = 512) -> None:
        self._default_ttl = float(default_ttl)
        self._max_entries = int(max_entries)
        self._store: dict[Hashable, _Entry] = {}
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Any | None:
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            if entry.expires_at < now:
                # expired — evict on read
                self._store.pop(key, None)
                return None
            return entry.value

    def get_stale_ok(self, key: Hashable) -> tuple[Any | None, bool]:
        """Return (value, is_stale). Returns expired entries with is_stale=True.

        Used by endpoints that want sub-50ms responses even on cold caches,
        paid for by accepting "data from N seconds ago" on the first call
        while a refresh runs in the background.
        """
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None, False
            is_stale = entry.expires_at < now
            return entry.value, is_stale

    def set(self, key: Hashable, value: Any, ttl: float | None = None) -> None:
        ttl_value = self._default_ttl if ttl is None else float(ttl)
        with self._lock:
            # cheap LRU-ish eviction: if we're at the cap, drop the oldest expired
            if len(self._store) >= self._max_entries:
                self._evict_one_locked()
            now = time.monotonic()
            self._store[key] = _Entry(
                value=value,
                expires_at=now + ttl_value,
            )

    def invalidate(self, key: Hashable) -> None:
        with self._lock:
            self._store.pop(key, None)

    def invalidate_prefix(self, prefix: tuple) -> int:
        """Drop every entry whose key starts with ``prefix`` (for keys that are tuples)."""
        dropped = 0
        with self._lock:
            for k in list(self._store.keys()):
                if isinstance(k, tuple) and len(k) >= len(prefix) and k[: len(prefix)] == prefix:
                    self._store.pop(k, None)
                    dropped += 1
        return dropped

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def _evict_one_locked(self) -> None:
        now = time.monotonic()
        # First try to evict an expired entry; otherwise drop the oldest.
        for k, e in list(self._store.items()):
            if e.expires_at < now:
                self._store.pop(k, None)
                return
        # No expired entry — drop the oldest (first inserted).
        try:
            oldest_key = next(iter(self._store))
            self._store.pop(oldest_key, None)
        except StopIteration:
            pass


# Module-level caches. Import these directly.
snapshot_cache = TTLCache(default_ttl=30.0, max_entries=256)
"""Broker snapshot cache. Keys: ``("snapshot", user_id, broker_id)``."""

prefs_cache = TTLCache(default_ttl=60.0, max_entries=512)
"""User preferences cache. Keys: ``("prefs", user_id)``."""
