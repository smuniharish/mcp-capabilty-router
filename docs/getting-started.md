# Getting started

This guide builds a complete integration step by step: connect a server, discover
its capabilities, route requests to them, and hand the right tools to an agent.

## Install

```bash
pip install mcp-capability-router
```

The package requires Python 3.12 or newer and installs FastMCP, LangChain, and
refresh-engine. Install the LangChain integration of your model provider, such as
`langchain-openai` or `langchain-anthropic`, to run agents.

## Create a runtime

`MCPRuntime` is the entry point. It owns the servers you register, their
connections, the capability registry, the retriever, the circuit breakers, and every
background task. Use it as an asynchronous context manager so that everything is
released when you are done:

```python
from mcp_capability_router import MCPRuntime

async with MCPRuntime() as runtime:
    ...
```

Create one runtime per tenant, agent, or trust boundary; runtimes share nothing.

## Register servers

`register_mcp` registers any server that [FastMCP](https://gofastmcp.com) can reach:

```python
from fastmcp.client.transports import NpxStdioTransport

await runtime.register_mcp("docs", "https://docs.example.com/mcp")
await runtime.register_mcp("local", "./servers/inventory.py")
await runtime.register_mcp(
    "files", NpxStdioTransport("@modelcontextprotocol/server-filesystem", ["/data"])
)
```

The first argument is the server ID: 1 to 64 letters, digits, hyphens, or
underscores, starting with a letter or a digit. Registration connects to nothing.
The runtime opens a connection when an operation first needs the server, and keeps
it open until the server is unregistered or the runtime closes.

## Discover capabilities

`refresh_server` lists the tools, resources, and prompts of a server and stores their
metadata in the registry. Each capability gets an ID of the form
`<server_id>:<type>:<name>`, such as `docs:tool:search_docs`, where the name of a
resource is its URI. To discover a server as soon as it is registered, pass a refresh
policy instead:

```python
from mcp_capability_router import RefreshPolicy

await runtime.register_mcp(
    "docs", "https://docs.example.com/mcp", refresh=RefreshPolicy(on_register=True)
)
```

Refresh policies can also refresh on a schedule, on change notifications, or when a
query finds nothing; see [Discovery and refresh](guides/refresh.md).

## Retrieve and use capabilities

`retrieve` ranks the stored metadata against a request without calling any server.
`execute` calls a tool, `read_resource` reads a resource, and `get_prompt` renders a
prompt. This program puts it all together with an in-process server:

<!-- test -->
```python
import asyncio

from fastmcp import FastMCP

from mcp_capability_router import CapabilityType, MCPRuntime

support = FastMCP("support")
TICKETS = {"T-1": "Printer offline", "T-2": "VPN drops every hour"}


@support.tool(tags={"tickets"})
def search_tickets(text: str) -> list[str]:
    """Search support tickets by their summary."""
    return [key for key, summary in TICKETS.items() if text.lower() in summary.lower()]


@support.tool(tags={"tickets"})
def close_ticket(ticket_id: str) -> str:
    """Close a support ticket."""
    return f"closed {ticket_id}"


@support.resource("support://runbooks/vpn", description="How to fix VPN problems")
def vpn_runbook() -> str:
    return "Restart the VPN client, then renew the certificate."


@support.prompt(description="Draft a reply to a customer")
def reply(ticket_id: str) -> str:
    return f"Write a short, friendly reply about ticket {ticket_id}."


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_mcp("support", support)
        result = await runtime.refresh_server("support")
        print(f"discovered {result.added_count} capabilities")

        [tool] = await runtime.retrieve(
            "find tickets about the VPN", type=CapabilityType.TOOL, limit=1
        )
        message = await runtime.execute(tool.capability_id, {"text": "vpn"})
        print(f"{tool.name}: {message.artifact['structured_content']['result']}")

        [runbook] = await runtime.retrieve("vpn", type=CapabilityType.RESOURCE, limit=1)
        [contents] = await runtime.read_resource(runbook.capability_id)
        print(f"{runbook.name}: {contents.text}")

        prompt = await runtime.get_prompt("support:prompt:reply", {"ticket_id": "T-2"})
        print(f"prompt: {prompt.messages[0].content.text}")


asyncio.run(main())
```

Running the program prints:

```text
discovered 4 capabilities
search_tickets: ['T-2']
vpn_runbook: Restart the VPN client, then renew the certificate.
prompt: Write a short, friendly reply about ticket T-2.
```

With FastMCP, `execute` returns a LangChain `ToolMessage`: its `content` holds the
content blocks of the result and its `artifact` holds the structured content.
`read_resource` returns the MCP resource contents, and `get_prompt` returns the MCP
prompt result. A tool that reports an error raises `ToolExecutionError`.

## Make operations resilient

Every server operation runs through the resilience pipeline. Each server gets a
circuit breaker for each kind of operation by default; add a timeout and a retry
policy for production:

```python
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from mcp_capability_router import MCPRuntime, is_retryable

runtime = MCPRuntime(
    operation_timeout=30,
    retry=AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=0.2, max=5),
        retry=retry_if_exception(is_retryable),
    ),
)
```

`is_retryable` retries only failures that can succeed on another attempt, such as a
lost connection or an overloaded server, and never repeats a tool call that the tool
itself rejected. See [Resilience](guides/resilience.md).

## Give an agent routed tools

`CapabilityRoutingMiddleware` turns a LangChain agent into a router: before each model
call, it retrieves the tools that match the latest user message and adds them to the
call. Tool calls run through the runtime:

```python
from langchain.agents import create_agent

from mcp_capability_router import CapabilityRoutingMiddleware

agent = create_agent(
    "openai:gpt-5.4-mini",
    tools=[],
    middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
    system_prompt="You are a support assistant. Use the tools to answer.",
)
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "Which tickets mention the VPN?"}]}
)
```

For a fixed set of tools, such as in a LangGraph workflow, `as_tool` returns a
LangChain tool for one capability. See
[LangChain and LangGraph agents](guides/agents.md).

## Next steps

- [Concepts](concepts.md) explains how the pieces fit together.
- [Connecting MCP servers](guides/servers.md) covers transports, authentication, and
  custom adapters.
- [Production checklist](guides/production.md) lists what to verify before going
  live.
