"""mcp-approval server — Approval Gate MCP entry point (§3.4).

Usage:
    python -m winny.mcp.approval.server
    # or
    mcp-approval
"""

from __future__ import annotations

import asyncio

import winny.common.config  # noqa: F401  — load .env into os.environ
from winny.mcp.approval.tools import (
    consume_grant,
    list_pending_approvals,
    request_approval,
    revoke_approval,
    verify_approval,
)
from winny.mcp.base import McpServer, ToolDescriptor, ToolParam


def _build_server() -> McpServer:
    """Construct the mcp-approval server with tool registrations."""
    server = McpServer(name="mcp-approval", version="0.1.0")

    # ---------- request ----------
    server.register_tool(
        ToolDescriptor(
            name="request",
            description=(
                "Create a pending approval request for a user verdict. "
                "Returns approval_id, one_time_code, summary, and expiry."
            ),
            parameters=[
                ToolParam(
                    name="decision_id",
                    type="string",
                    description="The DecisionId that produced this order intent.",
                ),
                ToolParam(
                    name="order_intent",
                    type="object",
                    description="The OrderIntent dict (JSON-safe) to approve.",
                ),
                ToolParam(
                    name="ttl_seconds",
                    type="integer",
                    description="Time-to-live in seconds for the approval (max 300).",
                    required=False,
                    default=300,
                ),
                ToolParam(
                    name="summary",
                    type="string",
                    description="Human-readable summary shown to user. Auto-generated if omitted.",
                    required=False,
                ),
            ],
            handler=request_approval,
        )
    )

    # ---------- verify ----------
    server.register_tool(
        ToolDescriptor(
            name="verify",
            description=(
                "Validate user's one-time code and issue a signed ApprovalGrant. "
                "Called when user confirms with their code."
            ),
            parameters=[
                ToolParam(
                    name="approval_id",
                    type="string",
                    description="The ApprovalId from the request step.",
                ),
                ToolParam(
                    name="user_token",
                    type="string",
                    description="The one-time code the user received and is presenting.",
                ),
            ],
            handler=verify_approval,
        )
    )

    # ---------- consume ----------
    server.register_tool(
        ToolDescriptor(
            name="consume",
            description=(
                "Verify + consume a grant atomically. Called by submit_order before "
                "placing the order with the broker. After success, grant cannot be reused."
            ),
            parameters=[
                ToolParam(
                    name="approval_id",
                    type="string",
                    description="The ApprovalId.",
                ),
                ToolParam(
                    name="grant_token",
                    type="string",
                    description="The opaque grant_token from the verify step.",
                ),
                ToolParam(
                    name="order_intent_hash",
                    type="string",
                    description="sha256 of the canonical OrderIntent being submitted.",
                ),
                ToolParam(
                    name="by_caller",
                    type="string",
                    description="Identifier of the caller (e.g. 'mcp-algo').",
                    required=False,
                    default="mcp-algo",
                ),
            ],
            handler=consume_grant,
        )
    )

    # ---------- revoke ----------
    server.register_tool(
        ToolDescriptor(
            name="revoke",
            description=(
                "Revoke a pending approval. Cannot revoke already-consumed grants."
            ),
            parameters=[
                ToolParam(
                    name="approval_id",
                    type="string",
                    description="The ApprovalId to revoke.",
                ),
                ToolParam(
                    name="reason",
                    type="string",
                    description="Optional reason for revocation.",
                    required=False,
                    default="",
                ),
            ],
            handler=revoke_approval,
        )
    )

    # ---------- list_pending ----------
    server.register_tool(
        ToolDescriptor(
            name="list_pending",
            description="Return all non-expired pending approval requests.",
            parameters=[],
            handler=list_pending_approvals,
        )
    )

    return server


def main() -> None:
    """Entry point for mcp-approval."""
    server = _build_server()
    asyncio.run(server.run())


if __name__ == "__main__":
    main()
