"""Retries, circuit breaking, timeouts, interceptors, and health.

A custom adapter wraps the FastMCP adapter to simulate an unreliable server.
The runtime-wide `ResiliencePolicy` retries transient failures of idempotent
tools, opens the circuit of a server that keeps failing, and rate-limits every
attempt; the slow `reports` server gets its own policy with a short timeout.
Health is reported from the circuits, and unhealthy servers drop out of retrieval.
"""

import asyncio
import dataclasses
import logging
import sys
from collections.abc import Mapping
from typing import Any

from aiolimiter import AsyncLimiter
from common import crm_server
from fastmcp import FastMCP
from purgatory import AsyncCircuitBreakerFactory
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_none

from mcp_capability_router import (
    CallNext,
    CircuitOpenError,
    FastMCPAdapter,
    Interceptor,
    MCPRuntime,
    OperationContext,
    RefreshPolicy,
    ResiliencePolicy,
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


class Audit(Interceptor):
    """Prints the outcome of every tool call; interceptors may also be async functions."""

    async def __call__(self, context: OperationContext, call_next: CallNext, /) -> Any:
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
    logging.basicConfig(level=logging.WARNING, format="  log: %(message)s", stream=sys.stdout)
    flaky = UnreliableAdapter(crm_server(), failures=2)
    down = UnreliableAdapter(crm_server(), failures=1_000)

    slow = FastMCP("reports")

    @slow.tool
    async def build_report() -> str:
        """Build a long report."""
        await asyncio.sleep(5)
        return "done"

    resilience = ResiliencePolicy(
        # Only tools marked readOnlyHint or idempotentHint are retried, unless
        # retry_unsafe_tools is set: retrying any other call could repeat its effects.
        retry=AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_none(),
            retry=retry_if_exception(is_retryable),
        ),
        circuit_breaker=AsyncCircuitBreakerFactory(default_threshold=2, default_ttl=60),
        rate_limiter=AsyncLimiter(100, time_period=1),
        operation_timeout=10,
    )
    async with MCPRuntime(resilience=resilience, interceptors=[Audit()]) as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_server("flaky", lambda: flaky, refresh=policy)
        await runtime.register_server("down", lambda: down, refresh=policy)
        await runtime.register_mcp(
            "reports",
            slow,
            refresh=policy,
            resilience=dataclasses.replace(runtime.resilience, operation_timeout=0.2),
        )

        print("transient failures are retried:")
        result = await runtime.execute("flaky:tool:search_customers", {"query": "globex"})
        print(f"  found {result.data[0]['name']}")

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

        print("\nservers with an open circuit drop out of retrieval:")
        found = await runtime.retrieve("search customers")
        print(f"  {sorted({capability.server_id for capability in found})}")


if __name__ == "__main__":
    asyncio.run(main())
