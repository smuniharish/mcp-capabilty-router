# Integrations

The core needs no agent framework. Pick the narrowest integration that fits.

## Any framework: route_tools

```python
tools = await runtime.route_tools(request, limit=5)
for tool in tools:
    tool.name, tool.description, tool.input_schema  # what a model needs
result = await tool(arguments)  # runs through the runtime; a CallToolResult
```

- Names are `<server_id>_<tool>`; with `server_id="billing"`, the plain MCP names.
- `await runtime.resolve_tool(name)` maps a name a model called on an earlier
  turn back to its `RoutedTool`; it raises `InvalidRequestError` when the name is
  ambiguous between servers.
- `where=lambda tool: not tool.destructive` hides tools from routing.
- `await runtime.tool(capability_id)` returns a fixed `RoutedTool`.
- Convert to the framework's tool type with `name`, `description`, and
  `input_schema`. The OpenAI SDK takes
  `{"type": "function", "function": {"name", "description", "parameters"}}`.
- Return `result.structured_content` (as JSON) or the text blocks of
  `result.content` to the model; catch `MCPCapabilityRouterError` and return its
  message so the model can recover.

## Any MCP client: the gateway

Frameworks that speak MCP connect to `runtime.as_mcp_server()`; see
[gateway.md](gateway.md).

## LangChain, LangGraph, Deep Agents (`langchain` extra)

```python
from langchain.agents import create_agent

from mcp_capability_router.integrations.langchain import CapabilityRoutingMiddleware

agent = create_agent(
    model,
    tools=[],
    middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
    system_prompt="Use the tools to answer.",
)
result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})
```

- Before every model call, the middleware routes tools with the latest user
  message and adds them next to the agent's own tools. The model never sees the
  whole catalog.
- Calls run through the runtime. Router errors and timeouts return as error tool
  messages, so the model can recover.
- The middleware is asynchronous: use `ainvoke` or `astream`, never `invoke`.
- Pair it with `RefreshPolicy(on_query_miss=True)` so that new tools are found.
- Human approval: add `HumanInTheLoopMiddleware(interrupt_on={"billing_issue_refund": True})`
  after the routing middleware, with a checkpointer.
- Put retries in the runtime, not in `ToolRetryMiddleware`, so that they are
  classified and counted by circuits.
- Deep Agents: `create_deep_agent(model=model, middleware=[CapabilityRoutingMiddleware(runtime)])`.
- Multi-agent systems: scope each agent with `server_id="crm"`, for example in a
  `langgraph_swarm.create_swarm` network. Use separate runtimes for separate
  trust boundaries.
- Fixed tool sets: `to_langchain_tool(await runtime.tool(capability_id))` returns a
  `StructuredTool` for `model.bind_tools(...)` and LangGraph `ToolNode`.
- Gateway tools as LangChain tools: `await mcp_client_tools(fastmcp_client)`.
- Embeddings: `QdrantRetriever(embedder=LangChainEmbedder(embeddings))`.
- A LangChain vector store as the retriever: `VectorStoreRetriever(embeddings)`
  or `VectorStoreRetriever(vector_store=store)`, with an optional `reranker`.

## LangGraph workflows

Call the runtime from nodes for deterministic, auditable routing:

```python
async def route(state: State) -> dict[str, str]:
    [match] = await runtime.query(state.request, type=CapabilityType.TOOL, limit=1)
    return {"capability_id": match.capability_id}


async def act(state: State) -> dict[str, object]:
    result = await runtime.execute(state.capability_id, state.arguments)
    return {"result": result.data}
```

`read_resource` and `get_prompt` work the same way for resources and prompts.

## Other frameworks

Agno, CrewAI, and others: use `route_tools` or the gateway. A dedicated
integration belongs in `mcp_capability_router.integrations.<framework>` behind
an extra, converting `RoutedTool` to the framework's tool type.