"""Gateway event bus + WebSocket broadcaster.

A thin pub/sub layer that decouples event producers (REST routes, background
pollers) from the WebSocket fan-out. Producers call `bus.publish({...})` and
return; a single background task drains the queue and pushes every event to
every connected client.

Why a bus?
  - REST handlers stay synchronous-feeling — they don't await a fan-out.
  - One serialization, N sends — broadcast cost is paid once per event.
  - Dead connections are reaped lazily on send failure.
  - Background pollers (portfolio diff, pending-approvals scan) share the same path.

Envelope types — frontend `lib/stream.js` recognizes these:
  agent_message       {agent, text, ts}
  agent_response      {data}
  approval_request    {data: ApprovalRequest}
  approval_granted    {approval_id, expires_at}
  approval_revoked    {approval_id, reason}
  order_submitted     {data: OrderState}
  order_cancelled     {broker_order_id}
  portfolio_update    {data: PortfolioSnapshot}
  signal_new          {data: Signal}
  fill                {data: Fill}
  pnl_tick            {nav, ts}
  error               {message}
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import WebSocket

from winny_gateway.logging import get_logger

logger = get_logger(__name__)


class EventBus:
    """Pub/sub bus + WS connection registry.

    One instance per app, attached to `app.state.event_bus`. Producers call
    `publish(event)` from anywhere; the broadcaster loop reads from the queue
    and fans out to every registered WebSocket.
    """

    def __init__(self, max_queue: int = 1024) -> None:
        self._connections: set[WebSocket] = set()
        # Per-connection identity so events can be targeted to one user. A
        # missing entry means "unidentified" — such a socket only receives
        # explicitly-global events (user_id=None), never another user's data.
        self._user_by_ws: dict[WebSocket, str] = {}
        self._queue: asyncio.Queue[tuple[dict[str, Any], str | None]] = asyncio.Queue(maxsize=max_queue)
        self._task: asyncio.Task[None] | None = None

    # ── connection lifecycle ─────────────────────────────────────────────

    async def connect(self, ws: WebSocket, user_id: str | None = None) -> None:
        await ws.accept()
        self._connections.add(ws)
        if user_id:
            self._user_by_ws[ws] = user_id
        logger.info("WS client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        self._user_by_ws.pop(ws, None)
        logger.info("WS client disconnected (%d remaining)", len(self._connections))

    @property
    def connection_count(self) -> int:
        return len(self._connections)

    def connected_user_ids(self) -> set[str]:
        """Distinct user ids with at least one live connection."""
        return set(self._user_by_ws.values())

    # ── publish (sync-friendly) ──────────────────────────────────────────

    def publish(self, event: dict[str, Any], *, user_id: str | None = None) -> None:
        """Enqueue an event for fan-out. Non-blocking; drops on overflow.

        If ``user_id`` is given, only that user's connections receive it
        (multi-tenant isolation). If ``None``, every connection receives it —
        reserve that for genuinely-global data (market ticks, system notices),
        never for account/order/approval payloads.

        Always stamps `ts` if absent. Callers should not block on this.
        """
        if "ts" not in event:
            event["ts"] = datetime.now(UTC).isoformat()
        try:
            self._queue.put_nowait((event, user_id))
        except asyncio.QueueFull:
            logger.warning("Event bus queue full — dropping event type=%s", event.get("type"))

    # ── broadcaster loop ─────────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the broadcaster background task."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="event-broadcaster")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        logger.info("Event broadcaster started")
        while True:
            try:
                event, target_user_id = await self._queue.get()
            except asyncio.CancelledError:
                logger.info("Event broadcaster stopping")
                raise

            payload = json.dumps(event, default=str)
            dead: list[WebSocket] = []
            for ws in list(self._connections):
                # Targeted events go only to the owning user's sockets.
                if target_user_id is not None and self._user_by_ws.get(ws) != target_user_id:
                    continue
                try:
                    await ws.send_text(payload)
                except Exception as exc:
                    logger.debug("WS send failed (%s); reaping", exc)
                    dead.append(ws)
            for ws in dead:
                self._connections.discard(ws)
                self._user_by_ws.pop(ws, None)


# ─── Background pollers ──────────────────────────────────────────────────────


async def portfolio_poller(
    bus: EventBus,
    pool: Any,
    interval_seconds: float = 5.0,
) -> None:
    """Push each connected user THEIR OWN portfolio on change.

    Multi-tenant safe: instead of broadcasting one (operator) snapshot to every
    socket, we iterate the connected users and push each their cached, scoped
    snapshot — the same per-(user, broker) cache the REST `/broker/snapshot`
    path populates. We only read the cache here (no fresh broker calls), so the
    push is a cheap supplement to the frontend's own 5s REST poll; if a user's
    cache is cold we simply skip until REST warms it.
    """
    import hashlib

    from winny_gateway.cache import snapshot_cache
    from winny_gateway.routes.settings import _get_prefs

    last_hash: dict[str, str] = {}

    while True:
        try:
            for user_id in bus.connected_user_ids():
                try:
                    broker = _get_prefs(user_id).get("broker_cr", "binance")
                    val, _stale = snapshot_cache.get_stale_ok(("snapshot", user_id, broker))
                    if not val:
                        continue
                    snap = val.get("data", val) if isinstance(val, dict) else val
                    blob = json.dumps(snap, default=str, sort_keys=True)
                    h = hashlib.sha256(blob.encode()).hexdigest()
                    if last_hash.get(user_id) == h:
                        continue
                    last_hash[user_id] = h
                    bus.publish({"type": "portfolio_update", "data": snap}, user_id=user_id)
                    try:
                        raw_nav = snap.get("nav_estimate") or snap.get("nav") if isinstance(snap, dict) else 0
                        bus.publish({"type": "pnl_tick", "nav": float(raw_nav or 0)}, user_id=user_id)
                    except (TypeError, ValueError):
                        pass
                except Exception as exc:
                    logger.debug("portfolio poller (user %s): %s", user_id[:8], exc)
            # Forget hashes for users who fully disconnected.
            live = bus.connected_user_ids()
            for uid in [u for u in last_hash if u not in live]:
                last_hash.pop(uid, None)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("portfolio poller: %s", exc)

        await asyncio.sleep(interval_seconds)


async def approvals_poller(
    bus: EventBus,
    pool: Any,
    interval_seconds: float = 3.0,
) -> None:
    """Watch the pending-approvals queue and notify ONLY the owning user.

    De-duplicates by approval_id; only fires once per request. Pairs with the
    REST `POST /approvals/request` route, which publishes inline — the poller
    is the fallback when approvals are created without a gateway hop. The
    one_time_code is redacted and the event is targeted to the approval's owner
    (via approval_state), so a code never reaches another tenant's socket.
    """
    from winny_gateway.approval_state import owner_of

    seen: set[str] = set()

    while True:
        try:
            result = await pool.get("approval").call_tool("list_pending", {})
            pending = result.get("pending", []) if isinstance(result, dict) else []
            if isinstance(pending, list):
                current: set[str] = set()
                for req in pending:
                    aid = req.get("approval_id") if isinstance(req, dict) else None
                    if not aid:
                        continue
                    current.add(aid)
                    if aid not in seen:
                        owner = owner_of(str(aid))
                        if owner is None:
                            # Untracked (legacy/operator) approval — no owner to
                            # target safely; skip the WS push rather than leak.
                            continue
                        public = {
                            k: v for k, v in req.items()
                            if k not in ("one_time_code", "otc", "user_token")
                        }
                        bus.publish({"type": "approval_request", "data": public}, user_id=owner)
                seen = current
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("approvals poller: %s", exc)

        await asyncio.sleep(interval_seconds)
