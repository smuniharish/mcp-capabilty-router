# Isolation and security

MCP servers reach real systems on behalf of models. This guide covers how the router
keeps tenants apart, how to handle credentials, and how to limit what agents can do.

## Isolate tenants with runtimes

A runtime owns everything it uses: servers and their connections, the registry,
retrieval caches, circuit breakers, rate limits, schedulers, and background tasks.
Runtimes share nothing, so create one per tenant, agent, or trust boundary:

![Isolation](../assets/diagrams/isolation-light.png#only-light)
![Isolation](../assets/diagrams/isolation-dark.png#only-dark)

```python
async with MCPRuntime() as tenant_a, MCPRuntime() as tenant_b:
    await tenant_a.register_mcp("crm", crm_for(tenant="a"))
    await tenant_b.register_mcp("crm", crm_for(tenant="b"))
```

A tenant can retrieve and call only the capabilities of its own runtime. Sharing is
always explicit: a durable registry or shared circuit-breaker storage passed to
several runtimes. Share them only within one trust boundary, such as between replicas
of the same service.

## Handle credentials

- Pass credentials through the target of `register_mcp`, such as
  `Client(url, auth=token)` or transport headers. Never put them in tool arguments,
  prompts, or capability metadata, which models can see.
- Give each tenant its own credentials in its own runtime.
- For short-lived tokens, register a factory that reads the current token. The runtime
  calls it again on `reconnect` and after a lost connection:

```python
from fastmcp import Client

from mcp_capability_router import FastMCPAdapter


def crm_adapter() -> FastMCPAdapter:
    return FastMCPAdapter(
        Client("https://crm.example.com/mcp", auth=vault.token("crm"))
    )


await runtime.register_server("crm", crm_adapter)
```

The router never logs tool arguments, results, or credentials, and its metrics carry
only identifiers, such as server IDs, operation names, outcomes, and states.

## Restrict tools

MCP tools can declare annotations, such as `readOnlyHint` and `destructiveHint`. The
router keeps them in `capability.metadata["annotations"]`, as `read_only_hint` and
`destructive_hint`, so that policies can act on them. An interceptor enforces a policy
for every caller, agent or not:

<!-- test -->
```python
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp import FastMCP

from mcp_capability_router import (
    AuthorizationError,
    MCPRuntime,
    Operation,
    OperationContext,
    RefreshPolicy,
)

crm = FastMCP("crm")


@crm.tool(annotations={"readOnlyHint": True})
def find_customer(name: str) -> str:
    """Find a customer by name."""
    return f"found {name}"


@crm.tool
def delete_customer(name: str) -> str:
    """Delete a customer."""
    return f"deleted {name}"


async def read_only(
    context: OperationContext, call_next: Callable[[], Awaitable[Any]]
) -> Any:
    capability = context.capability
    if context.operation is Operation.CALL_TOOL and capability is not None:
        if not capability.metadata.get("annotations", {}).get("read_only_hint"):
            msg = f"{capability.capability_id} may change data"
            raise AuthorizationError(msg)
    return await call_next()


async def main() -> None:
    async with MCPRuntime(interceptors=[read_only]) as runtime:
        await runtime.register_mcp("crm", crm, refresh=RefreshPolicy(on_register=True))
        message = await runtime.execute("crm:tool:find_customer", {"name": "Acme"})
        print(message.text)
        try:
            await runtime.execute("crm:tool:delete_customer", {"name": "Acme"})
        except AuthorizationError as error:
            print(f"rejected: {error}")


asyncio.run(main())
```

```text
found Acme
rejected: crm:tool:delete_customer may change data
```

`AuthorizationError` is not retried and does not count toward the circuit breaker, so
a rejected call leaves the server healthy. Annotations are hints from the server:
enforce policies on servers that you trust, and use explicit allow-lists of capability
IDs where it matters.

Other controls:

- Scope an agent to the servers it needs with
  `CapabilityRoutingMiddleware(runtime, server_id=...)`, or with a separate runtime.
- Require a human approval for destructive tools with LangChain's
  `HumanInTheLoopMiddleware`; see
  [LangChain and LangGraph agents](agents.md#combine-with-langchain-middleware).
- Bound the damage of runaway agents with `max_concurrency`, `rate_limiter`, and
  `operation_timeout`.

## Treat server content as untrusted

Tool descriptions, resource contents, prompt templates, and tool results come from
servers and reach models. A compromised or malicious server can use them for prompt
injection.

- Register only servers that you trust, and pin the versions of local servers.
- Automatic refreshes add new tools as soon as a server offers them. For servers
  outside your control, refresh manually after reviewing their changes, or filter
  capabilities with an allow-list.
- Local servers launched over stdio run with the permissions of your process. Scope
  them, for example the Filesystem server to one directory, and run them in a
  container when they need more.

## Report a vulnerability

Report security issues privately, as described in the
[security policy](https://github.com/smuniharish/mcp-capabilty-router/blob/master/SECURITY.md).
