"""MCP stdio bridge — spawn MCP servers and call tools via JSON-RPC 2.0."""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import uuid
from typing import Any

from winny_gateway.logging import get_logger

logger = get_logger(__name__)


def _to_argv(cmd: str | list[str]) -> list[str]:
    """Normalize a command into an argv list.

    A list is used verbatim (the app builds ``[sys.executable, "-m", module]``
    so MCP servers run under the current interpreter with no PATH dependency).
    A string is tokenized with shlex; on Windows we keep ``posix=False`` so
    backslash paths survive, otherwise POSIX rules apply.
    """
    if isinstance(cmd, list):
        return cmd
    return shlex.split(cmd, posix=(os.name != "nt"))


class McpBridge:
    """Manages a subprocess running an MCP server over stdio."""

    def __init__(self, cmd: str | list[str], name: str) -> None:
        self._argv = _to_argv(cmd)
        self._cmd = cmd if isinstance(cmd, str) else " ".join(cmd)
        self._name = name
        self._proc: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._reader_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Spawn the MCP server subprocess."""
        logger.info("Starting MCP bridge: %s (%s)", self._name, self._cmd)
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self._argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            self._reader_task = asyncio.create_task(self._read_loop())
            # Send initialize
            await self.call("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}})
            logger.info("MCP bridge %s initialized", self._name)
        except FileNotFoundError:
            logger.warning("MCP server command not found: %s — bridge will return stubs", self._cmd)
            self._proc = None
        except Exception as exc:
            # A server that spawns but crashes on import (e.g. timesfm without
            # torch) must not take the whole gateway down — degrade to stub mode.
            logger.warning("MCP server %s failed to initialize (%s) — bridge will return stubs", self._name, exc)
            if self._reader_task:
                self._reader_task.cancel()
            self._proc = None

    async def stop(self) -> None:
        """Terminate the subprocess."""
        if self._reader_task:
            self._reader_task.cancel()
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Send a JSON-RPC 2.0 request and await the response."""
        if self._proc is None or self._proc.stdin is None:
            # Stub mode
            return {"error": f"MCP server {self._name} not available"}

        req_id = str(uuid.uuid4())
        request = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        payload = json.dumps(request) + "\n"

        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[req_id] = future

        self._proc.stdin.write(payload.encode())
        await self._proc.stdin.drain()

        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except TimeoutError:
            self._pending.pop(req_id, None)
            return {"error": f"Timeout calling {method} on {self._name}"}

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a specific tool on the MCP server."""
        return await self.call("tools/call", {"name": tool_name, "arguments": arguments or {}})

    async def safe_call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        fallback: Any = None,
    ) -> Any:
        """Call a tool; on MCP-down/timeout, return `fallback` instead of an error dict.

        Routes that want graceful empty-state degradation should use this and pass
        an appropriate fallback (`[]` for list endpoints, `{}` for object endpoints).
        Routes that want to fail loudly should call `call_tool` directly and let
        the caller decide.
        """
        result = await self.call_tool(tool_name, arguments)
        if isinstance(result, dict) and "error" in result and len(result) <= 2:
            # MCP stub response or short error envelope — fall back so the route
            # can return an empty/known shape and the frontend doesn't choke on
            # an unexpected object where it expected a list.
            logger.warning(
                "MCP %s.%s returned error envelope: %s; using fallback",
                self._name, tool_name, result.get("error"),
            )
            return fallback if fallback is not None else result
        return result

    async def list_tools(self) -> dict[str, Any]:
        """List available tools."""
        return await self.call("tools/list", {})

    async def _read_loop(self) -> None:
        """Read JSON-RPC responses from stdout."""
        if self._proc is None or self._proc.stdout is None:
            return
        try:
            async for line in self._proc.stdout:
                try:
                    msg = json.loads(line)
                    req_id = msg.get("id")
                    if req_id and req_id in self._pending:
                        future = self._pending.pop(req_id)
                        if not future.done():
                            future.set_result(msg.get("result", msg))
                except json.JSONDecodeError:
                    continue
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("MCP reader error on %s: %s", self._name, exc)


class McpPool:
    """Pool of MCP bridges keyed by server name."""

    def __init__(self) -> None:
        self._bridges: dict[str, McpBridge] = {}

    def register(self, name: str, cmd: str | list[str]) -> None:
        self._bridges[name] = McpBridge(cmd, name)

    async def start_all(self) -> None:
        await asyncio.gather(*(b.start() for b in self._bridges.values()))

    async def stop_all(self) -> None:
        await asyncio.gather(*(b.stop() for b in self._bridges.values()))

    def get(self, name: str) -> McpBridge:
        bridge = self._bridges.get(name)
        if bridge is None:
            raise KeyError(f"No MCP bridge registered for '{name}'")
        return bridge
