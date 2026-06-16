"""MCP server base — stdio JSON-RPC 2.0 transport per §11.2.

All Winny MCP servers share this base class. They are spawned as subprocesses
of the Hermes agent (§2.2) and communicate via stdin/stdout with the MCP
protocol (JSON-RPC 2.0, one JSON object per line, newline-delimited).

Protocol flow:
    1. Client sends `initialize` → server responds with capabilities
    2. Client sends `tools/list` → server responds with tool descriptors
    3. Client sends `tools/call` → server runs tool, responds with result
    4. Repeat 3 until client sends `shutdown`

This base handles the transport layer. Subclasses register tools via the
`@tool` decorator and implement the business logic.
"""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class ToolParam:
    """Schema for a single tool parameter."""

    name: str
    type: str  # JSON Schema type
    description: str
    required: bool = True
    default: Any = None
    enum: list[str] | None = None
    items: dict[str, Any] | None = None  # for array types


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    """Registered tool metadata."""

    name: str
    description: str
    parameters: list[ToolParam]
    handler: Callable[..., Coroutine[Any, Any, Any]]


@dataclass
class McpServer:
    """Base MCP server with JSON-RPC 2.0 stdio transport.

    Usage:
        server = McpServer(name="mcp-timesfm", version="0.1.0")
        server.register_tool(descriptor)
        await server.run()
    """

    name: str
    version: str
    _tools: dict[str, ToolDescriptor] = field(default_factory=dict, init=False)
    _running: bool = field(default=False, init=False)

    def register_tool(self, descriptor: ToolDescriptor) -> None:
        """Register a tool handler."""
        self._tools[descriptor.name] = descriptor

    async def run(self) -> None:
        """Main loop: read JSON-RPC from stdin, dispatch, write to stdout.

        Reads are done with a blocking ``sys.stdin.buffer.readline()`` dispatched
        to a worker thread. This is intentionally NOT
        ``loop.connect_read_pipe(sys.stdin.buffer)``: on Windows the Proactor
        event loop cannot wrap an anonymous stdin pipe (it calls ``recv_into`` on
        a non-socket handle and raises in ``_ProactorReadPipeTransport``), so the
        stdio handshake silently times out. A thread-backed readline works
        identically on Linux/macOS/Windows for a single-client stdio server.
        """
        self._running = True
        logger.info("mcp_server_starting", name=self.name, version=self.version)

        loop = asyncio.get_running_loop()

        while self._running:
            line = await loop.run_in_executor(None, sys.stdin.buffer.readline)
            if not line:
                break  # EOF — parent process closed pipe

            try:
                msg = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as e:
                self._write_error(None, -32700, f"Parse error: {e}")
                continue

            await self._dispatch(msg)

        logger.info("mcp_server_stopped", name=self.name)

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """Route a JSON-RPC message to the appropriate handler."""
        method = msg.get("method", "")
        msg_id = msg.get("id")
        params = msg.get("params", {})

        if method == "initialize":
            self._write_result(
                msg_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": self.version},
                },
            )
        elif method == "notifications/initialized":
            pass  # client ack, no response needed
        elif method == "tools/list":
            self._write_result(msg_id, {"tools": self._list_tools()})
        elif method == "tools/call":
            await self._handle_tool_call(msg_id, params)
        elif method == "shutdown":
            self._write_result(msg_id, None)
            self._running = False
        else:
            self._write_error(msg_id, -32601, f"Method not found: {method}")

    async def _handle_tool_call(self, msg_id: Any, params: dict[str, Any]) -> None:
        """Execute a tool and return the result."""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        descriptor = self._tools.get(tool_name)
        if descriptor is None:
            self._write_error(msg_id, -32602, f"Unknown tool: {tool_name}")
            return

        try:
            start = datetime.now(UTC)
            result = await descriptor.handler(**arguments)
            elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000

            logger.info(
                "tool_call_success",
                tool=tool_name,
                elapsed_ms=round(elapsed_ms, 1),
            )
            self._write_result(
                msg_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, default=str)}],
                    "isError": False,
                },
            )
        except Exception as e:
            logger.error(
                "tool_call_error",
                tool=tool_name,
                error=str(e),
                traceback=traceback.format_exc(),
            )
            self._write_result(
                msg_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "error": type(e).__name__,
                                    "message": str(e),
                                }
                            ),
                        }
                    ],
                    "isError": True,
                },
            )

    def _list_tools(self) -> list[dict[str, Any]]:
        """Generate MCP tool descriptors for tools/list."""
        tools = []
        for desc in self._tools.values():
            properties: dict[str, Any] = {}
            required: list[str] = []
            for p in desc.parameters:
                prop: dict[str, Any] = {"type": p.type, "description": p.description}
                if p.enum:
                    prop["enum"] = p.enum
                if p.items:
                    prop["items"] = p.items
                if p.default is not None:
                    prop["default"] = p.default
                properties[p.name] = prop
                if p.required:
                    required.append(p.name)

            tools.append(
                {
                    "name": desc.name,
                    "description": desc.description,
                    "inputSchema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }
            )
        return tools

    def _write_result(self, msg_id: Any, result: Any) -> None:
        """Write a JSON-RPC success response to stdout."""
        response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
        self._write(response)

    def _write_error(self, msg_id: Any, code: int, message: str) -> None:
        """Write a JSON-RPC error response to stdout."""
        response = {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}
        self._write(response)

    def _write(self, obj: dict[str, Any]) -> None:
        """Write a single JSON line to stdout."""
        line = json.dumps(obj, separators=(",", ":"), default=str) + "\n"
        sys.stdout.buffer.write(line.encode("utf-8"))
        sys.stdout.buffer.flush()
