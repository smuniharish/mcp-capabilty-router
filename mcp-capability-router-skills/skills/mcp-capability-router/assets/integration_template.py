"""Template for a production mcp-capability-router integration.

Copy this file into the application, then adapt every place marked "Adapt:".
As written, it routes requests to an in-process demo server, shows a policy
rejecting a destructive tool, and reports health and metrics:

    python integration_template.py
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from aiolimiter import AsyncLimiter
from fastmcp import FastMCP
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from refresh_engine import InMemoryMetrics
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from mcp_capability_router import (
    AuthorizationError,
    CapabilityRoutingMiddleware,
    CapabilityType,
    MCPRuntime,
    Operation,
    OperationContext,
    RefreshPolicy,
    is_retryable,
)

# Adapt: tools that may change data and are allowed anyway.
ALLOWED_WRITES = frozenset({"helpdesk:tool:close_ticket"})


def demo_server() -> FastMCP:
    """Return an in-process MCP server for the demonstration.

    Adapt: delete this function, and register real servers in `open_runtime`.
    """
    server = FastMCP("helpdesk")

    @server.tool(annotations={"readOnlyHint": True})
    def search_tickets(text: str) -> list[str]:
        """Search support tickets by their summary."""
        return ["T-2"] if "vpn" in text.lower() else []

    @server.tool(annotations={"destructiveHint": True})
    def close_ticket(ticket_id: str) -> str:
        """Close a support ticket."""
        return f"closed {ticket_id}"

    @server.tool(annotations={"destructiveHint": True})
    def delete_ticket(ticket_id: str) -> str:
        """Delete a support ticket permanently."""
        return f"deleted {ticket_id}"

    return server


async def enforce_write_policy(
    context: OperationContext, call_next: Callable[[], Awaitable[Any]]
) -> Any:
    """Reject tool calls that may change data, unless they are allowed.

    Adapt: replace with the policy of the application.
    """
    capability = context.capability
    if context.operation is Operation.CALL_TOOL and capability is not None:
        read_only = capability.metadata.get("annotations", {}).get("read_only_hint")
        if not read_only and capability.capability_id not in ALLOWED_WRITES:
            msg = f"{capability.capability_id} may change data and is not allowed"
            raise AuthorizationError(msg)
    return await call_next()


@asynccontextmanager
async def open_runtime(metrics: InMemoryMetrics) -> AsyncGenerator[MCPRuntime, None]:
    """Create a runtime with production settings, and register its servers."""
    runtime = MCPRuntime(
        max_concurrency=32,
        operation_timeout=30,
        retry=AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(initial=0.2, max=5),
            retry=retry_if_exception(is_retryable),
        ),
        rate_limiter=AsyncLimiter(100, time_period=1),
        interceptors=[enforce_write_policy],
        # Adapt: use a sink that exports to the monitoring system.
        metrics=metrics,
    )
    async with runtime:
        # Adapt: register each real server under a stable ID, with its URL or
        # transport and credentials, and a refresh policy that suits it.
        policy = RefreshPolicy(on_register=True, on_query_miss=True, interval=900)
        await runtime.register_mcp("helpdesk", demo_server(), refresh=policy)
        yield runtime


def build_agent(runtime: MCPRuntime, model: BaseChatModel | str):
    """Return a LangChain agent that sees only the tools each turn needs.

    Invoke the agent with `await agent.ainvoke(...)`; the middleware is
    asynchronous.
    """
    return create_agent(
        model,
        tools=[],
        middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
        # Adapt: describe the assistant's job.
        system_prompt="You are a support assistant. Use the tools to answer.",
    )


async def main() -> None:
    """Route one request, try a forbidden tool, and report health and metrics."""
    metrics = InMemoryMetrics()
    async with open_runtime(metrics) as runtime:
        [tool] = await runtime.query(
            "find tickets about the VPN", type=CapabilityType.TOOL, limit=1
        )
        message = await runtime.execute(tool.capability_id, {"text": "VPN"})
        print(f"{tool.capability_id}: {message.text}")
        try:
            await runtime.execute("helpdesk:tool:delete_ticket", {"ticket_id": "T-2"})
        except AuthorizationError as error:
            print(f"rejected: {error}")
        for server_id in runtime.servers:
            print(f"health of {server_id}: {await runtime.health(server_id)}")
    counters, _ = metrics.snapshot()
    calls = sum(
        value
        for name, value in counters.items()
        if name.startswith("mcp_capability_router.operations{operation=call_tool,")
    )
    print(f"tool calls recorded: {calls}")


if __name__ == "__main__":
    # Adapt: configure logging once at application startup.
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
