"""Dashboard HTTP API for the google_meet plugin.

Auto-mounted at ``/api/plugins/google_meet/`` by the dashboard plugin system
(:func:`hermes_cli.web_server._mount_plugin_api_routes`). This lets the VIGIL
product's Meeting Room dispatch the Meet bot directly — paste a Google Meet
link, send the agent in — through the Supabase-gated operator proxy
(``web/api/ops.js``), with no separate agent loop in the path.

Every handler is a thin wrapper around the exact same functions the agent
tools call (``plugins.google_meet.tools.handle_meet_*``), so the HTTP surface
and the agent surface can never drift. Requests are gated by the dashboard
session token like all other ``/api/plugins/...`` routes.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body

from plugins.google_meet import tools

router = APIRouter()


def _call(fn, args: Dict[str, Any]) -> dict:
    """Run a tool handler (returns a JSON string) and parse it to a dict."""
    return json.loads(fn(args or {}))


@router.post("/join")
def join(payload: Dict[str, Any] = Body(default={})) -> dict:
    """Send the bot into a Meet. Body: {url, mode?, guest_name?, headed?, duration?}.

    ``mode`` is ``transcribe`` (default) or ``realtime`` (speaks via meet_say).
    """
    return _call(tools.handle_meet_join, payload)


@router.get("/status")
def status() -> dict:
    """Current bot state (joined / transcribing / error)."""
    return _call(tools.handle_meet_status, {})


@router.get("/transcript")
def transcript(last: Optional[int] = None) -> dict:
    """Scraped transcript; ``last`` returns only the last N caption lines."""
    return _call(tools.handle_meet_transcript, {"last": last} if last else {})


@router.post("/say")
def say(payload: Dict[str, Any] = Body(default={})) -> dict:
    """Speak text in an active realtime meeting. Body: {text}."""
    return _call(tools.handle_meet_say, payload)


@router.post("/leave")
def leave() -> dict:
    """Make the bot leave and stop the session."""
    return _call(tools.handle_meet_leave, {})
