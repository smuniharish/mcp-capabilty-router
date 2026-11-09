# Security

## Isolation

- One `MCPRuntime` per tenant, agent, or trust boundary. A runtime owns its servers,
  connections, registry, caches, circuits, limits, and background tasks, and shares
  none of them.
- Sharing is explicit: a durable registry or a shared circuit-breaker factory passed
  to several runtimes. Share only within one trust boundary.
- Scope agents to the servers they need with `route_tools(..., server_id=...)`,
  or `CapabilityRoutingMiddleware(runtime, server_id=...)` from
  `mcp_capability_router.integrations.langchain`.
- A gateway from `as_mcp_server` can call every registered tool: serve it over
  HTTP only behind authentication.

## Credentials

- Pass credentials through the target, such as `Client(url, auth=token)` or
  `StreamableHttpTransport(url, headers=...)`, or read them in an adapter factory:

```python
def crm_adapter() -> FastMCPAdapter:
    return FastMCPAdapter(Client("https://crm.example.com/mcp", auth=vault.token("crm")))


await runtime.register_server("crm", crm_adapter)
```

- Never put credentials in tool arguments, prompts, capability metadata, or logs.
- The router does not log tool arguments, results, or credentials; metrics carry only
  identifiers.

## Restrict tools

Tools expose their annotations as `read_only`, `destructive`, `idempotent`, and
`open_world`. Enforce policy in an interceptor so that it applies to every caller,
including the gateway:

```python
async def read_only(context: OperationContext, call_next: Callable[[], Awaitable[Any]]) -> Any:
    capability = context.capability
    if isinstance(capability, Tool) and not capability.read_only:
        msg = f"{capability.capability_id} may change data"
        raise AuthorizationError(msg)
    return await call_next()
```

- Annotations are hints from the server; prefer explicit allow-lists of capability
  IDs for servers you do not control.
- Require human approval for destructive tools with LangChain's
  `HumanInTheLoopMiddleware` and a checkpointer.
- Bound runaway agents with `max_concurrency`, `rate_limiter`, and
  `operation_timeout`.

## Untrusted content

- Tool descriptions, resource contents, prompts, and tool results reach models and can
  carry prompt injection. Register only trusted servers; pin versions of local
  servers.
- Automatic refreshes add new tools immediately. For servers outside your control,
  refresh manually after review, or filter with an allow-list.
- stdio servers run with the process's permissions; scope them, such as the
  Filesystem server to one directory, or run them in a container.
