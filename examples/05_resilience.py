"""Retries, circuit breaking, timeouts, interceptors, and health.

A custom adapter wraps the FastMCP adapter to simulate an unreliable server.
The runtime retries transient failures, opens the circuit of a server that keeps
failing, enforces a timeout per attempt, and reports health from the circuits.
"""

import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from aiolimiter import AsyncLimiter
from common import crm_server
from fastmcp import FastMCP
from purgatory import AsyncCircuitBreakerFactory
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_none

from mcp_capability_router import (
    CircuitOpenError,
    FastMCPAdapter,
    MCPRuntime,
    OperationContext,
    RefreshPolicy,
    ServerUnavailableError,
    ToolExecutionError,
    is_retryable,
)


class UnreliableAdapter(FastMCPAdapter):
    """Fails the first `failures` tool calls as if the server were overloaded."""

    def __init__(self, server: FastMCP, failures: int) -> None:
        super().__init__(server)
        self.failures = failures

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if self.failures:
            self.failures -= 1
            msg = "server overloaded"
            raise ServerUnavailableError(msg)
        return await super().call_tool(name, arguments)


async def audit(
    context: OperationContext, call_next: Callable[[], Awaitable[Any]]
) -> Any:
    operation = f"{context.operation} on {context.server_id}"
    try:
        result = await call_next()
    except Exception as error:
        print(f"  audit: {operation} -> {type(error).__name__}")
        raise
    print(f"  audit: {operation} -> ok")
    return result


async def main() -> None:
    # The runtime logs circuit transitions to the "mcp_capability_router" logger.
    logging.basicConfig(
        level=logging.WARNING, format="  log: %(message)s", stream=sys.stdout
    )
    flaky = UnreliableAdapter(crm_server(), failures=2)
    down = UnreliableAdapter(crm_server(), failures=1_000)

    slow = FastMCP("reports")

    @slow.tool
    async def build_report() -> str:
        """Build a long report."""
        await asyncio.sleep(5)
        return "done"

    async with MCPRuntime(
        retry=AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_none(),
            retry=retry_if_exception(is_retryable),
        ),
        circuit_breaker=AsyncCircuitBreakerFactory(default_threshold=2, default_ttl=60),
        operation_timeout=0.2,
        rate_limiter=AsyncLimiter(100, time_period=1),
        interceptors=[audit],
    ) as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_server("flaky", lambda: flaky, refresh=policy)
        await runtime.register_server("down", lambda: down, refresh=policy)
        await runtime.register_mcp("reports", slow, refresh=policy)

        print("transient failures are retried:")
        result = await runtime.execute(
            "flaky:tool:search_customers", {"query": "globex"}
        )
        print(f"  found {result.artifact['structured_content']['result'][0]['name']}")

        print("\nrepeated failures open the circuit:")
        for _ in range(3):
            try:
                await runtime.execute("down:tool:search_customers", {"query": "acme"})
            except (ServerUnavailableError, CircuitOpenError) as error:
                print(f"  {type(error).__name__}: {error}")

        print("\nslow attempts time out:")
        try:
            await runtime.execute("reports:tool:build_report")
        except TimeoutError as error:
            print(f"  TimeoutError: {error.__notes__[0]}")

        print("\ntool errors reach the caller but leave the server healthy:")
        try:
            await runtime.execute(
                "flaky:tool:update_customer_email",
                {"customer_id": "c-999", "email": "x@example.com"},
            )
        except ToolExecutionError as error:
            print(f"  ToolExecutionError: {error}")

        for server_id in runtime.servers:
            print(f"health of {server_id}: {await runtime.health(server_id)}")


if __name__ == "__main__":
    asyncio.run(main())
