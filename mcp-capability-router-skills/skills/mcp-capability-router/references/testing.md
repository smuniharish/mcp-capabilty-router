# Testing

Test integrations without network, subprocesses, credentials, or models.

## In-process servers

Register a `FastMCP` server object directly; operations use the real protocol and the
full pipeline:

```python
@pytest.fixture
async def runtime():
    async with MCPRuntime() as runtime:
        await runtime.register_mcp(
            "billing", billing_server(), refresh=RefreshPolicy(on_register=True)
        )
        yield runtime


async def test_routes(runtime: MCPRuntime) -> None:
    [tool] = await runtime.retrieve("invoices of a customer", limit=1)
    assert tool.capability_id == "billing:tool:list_invoices"
    message = await runtime.execute(tool.capability_id, {"customer_id": "c-100"})
    assert message.artifact["structured_content"] == {"result": ["inv-1"]}
```

- Use an async test runner, such as `pytest-asyncio` in auto mode.
- `KeywordRetriever` is deterministic; assert rankings exactly.
- Set `logging.getLogger("fastmcp").setLevel(logging.CRITICAL)` when tests trigger
  tool errors on purpose.

## Failures

Subclass `FastMCPAdapter`, or write a small `MCPAdapter`, that raises router errors
such as `ServerUnavailableError` or `ToolExecutionError`, and register it with
`register_server(server_id, lambda: adapter)`. Use small values to keep tests fast:
`AsyncCircuitBreakerFactory(default_threshold=2, default_ttl=60)`,
`operation_timeout=0.2`, and tenacity's `wait_none()`.

## Agents without a model

LangChain's `GenericFakeChatModel` raises on `bind_tools`; subclass it:

```python
class ScriptedModel(GenericFakeChatModel):
    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedModel":
        return self


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
agent = create_agent(
    model,
    tools=[],
    middleware=[CapabilityRoutingMiddleware(runtime, server_id="support")],
)
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "VPN tickets?"}]}
)
```

Assert on the `ToolMessage`s in `result["messages"]`: `name`, `status`, and `text`.

## Background refreshes

Wait for events instead of sleeping:

```python
refreshed = asyncio.Event()


def on_event(event: RefreshEvent) -> None:
    if event.kind is EventKind.REFRESH_COMPLETED:
        refreshed.set()


policy = RefreshPolicy(change_events=changes, event_handlers=(on_event,))
```

## Metrics

```python
metrics = InMemoryMetrics()
async with MCPRuntime(metrics=metrics) as runtime:
    ...
counters, durations = metrics.snapshot()
```

Counter keys look like
`mcp_capability_router.operations{operation=call_tool,outcome=success,server_id=crm}`.
