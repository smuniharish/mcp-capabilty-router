# Testing integrations

Integrations built on the router can be tested quickly and deterministically, without
network access, subprocesses, credentials, or models.

## Use in-process servers

Register a `FastMCP` server object directly. It runs in the test's event loop, and
every operation goes through the real MCP protocol and the full resilience pipeline:

```python
import pytest
from fastmcp import FastMCP

from mcp_capability_router import MCPRuntime, RefreshPolicy


def billing_server() -> FastMCP:
    server = FastMCP("billing")

    @server.tool
    def list_invoices(customer_id: str) -> list[str]:
        """List the invoices of a customer."""
        return ["inv-1"] if customer_id == "c-100" else []

    return server


@pytest.fixture
async def runtime():
    async with MCPRuntime() as runtime:
        await runtime.register_mcp(
            "billing", billing_server(), refresh=RefreshPolicy(on_register=True)
        )
        yield runtime


async def test_routes_invoice_requests(runtime: MCPRuntime) -> None:
    [tool] = await runtime.retrieve("invoices of a customer", limit=1)
    assert tool.capability_id == "billing:tool:list_invoices"
    message = await runtime.execute(tool.capability_id, {"customer_id": "c-100"})
    assert message.artifact["structured_content"] == {"result": ["inv-1"]}
```

Async tests need an async test runner, such as `pytest-asyncio` or `anyio`.
`KeywordRetriever`, the default retriever, is deterministic, so rankings can be
asserted exactly.

## Inject failures

To test how your application handles failures, subclass `FastMCPAdapter`, or write a
small adapter, and raise the router's exceptions:

```python
from collections.abc import Mapping
from typing import Any

from fastmcp import FastMCP

from mcp_capability_router import FastMCPAdapter, ServerUnavailableError


class FlakyAdapter(FastMCPAdapter):
    """Fails the first `failures` tool calls as if the server were overloaded."""

    def __init__(self, server: FastMCP, failures: int) -> None:
        super().__init__(server)
        self.failures = failures

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        if self.failures:
            self.failures -= 1
            raise ServerUnavailableError("server overloaded")
        return await super().call_tool(name, arguments)


adapter = FlakyAdapter(billing_server(), failures=2)
await runtime.register_server("billing", lambda: adapter)
```

Configure small thresholds and timeouts in tests, such as
`AsyncCircuitBreakerFactory(default_threshold=2)` and `operation_timeout=0.2`, so that
circuits open and timeouts expire quickly.

## Test agents without a model

LangChain's `GenericFakeChatModel` replies with scripted messages. Accept tools in
`bind_tools`, and the agent runs its full loop, including the routing middleware and
the tool calls through the runtime:

<!-- test -->
```python
import asyncio
from collections.abc import Sequence
from typing import Any

from fastmcp import FastMCP
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage

from mcp_capability_router import CapabilityRoutingMiddleware, MCPRuntime, RefreshPolicy


class ScriptedModel(GenericFakeChatModel):
    """Replies with scripted messages and accepts any tools."""

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedModel":
        return self


support = FastMCP("support")


@support.tool
def search_tickets(text: str) -> list[str]:
    """Search support tickets by their summary."""
    return ["T-2"] if "vpn" in text.lower() else []


async def main() -> None:
    model = ScriptedModel(
        messages=iter(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        {"name": "search_tickets", "args": {"text": "VPN"}, "id": "1"}
                    ],
                ),
                AIMessage("Ticket T-2 mentions the VPN."),
            ]
        )
    )
    async with MCPRuntime() as runtime:
        await runtime.register_mcp(
            "support", support, refresh=RefreshPolicy(on_register=True)
        )
        agent = create_agent(
            model,
            tools=[],
            middleware=[CapabilityRoutingMiddleware(runtime, server_id="support")],
        )
        result = await agent.ainvoke(
            {
                "messages": [
                    {"role": "user", "content": "Which tickets mention the VPN?"}
                ]
            }
        )
        for message in result["messages"]:
            if isinstance(message, ToolMessage):
                print(f"{message.name}: {message.status} {message.text}")
        print(result["messages"][-1].text)


asyncio.run(main())
```

```text
search_tickets: success ["T-2"]
Ticket T-2 mentions the VPN.
```

## Wait for background refreshes

Refreshes triggered by intervals and change events run in the background. Instead of
sleeping, wait for refresh-engine's completion event:

```python
import asyncio

from refresh_engine import EventKind, RefreshEvent

from mcp_capability_router import RefreshPolicy

refreshed = asyncio.Event()


def on_event(event: RefreshEvent) -> None:
    if event.kind is EventKind.REFRESH_COMPLETED:
        refreshed.set()


changes: asyncio.Queue[str] = asyncio.Queue()
policy = RefreshPolicy(change_events=changes, event_handlers=(on_event,))
await runtime.register_mcp("crm", server, refresh=policy)

server.add_tool(merge_customers)
await changes.put("tools changed")
await refreshed.wait()
```

## Assert metrics

Pass a `refresh_engine.InMemoryMetrics` sink and read its counters:

```python
from refresh_engine import InMemoryMetrics

metrics = InMemoryMetrics()
async with MCPRuntime(metrics=metrics) as runtime:
    ...
counters, durations = metrics.snapshot()
```
