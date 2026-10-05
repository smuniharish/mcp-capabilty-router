# Agents

## LangChain create_agent

```python
from langchain.agents import create_agent

from mcp_capability_router import CapabilityRoutingMiddleware

agent = create_agent(
    model,
    tools=[],
    middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
    system_prompt="Use the tools to answer.",
)
result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})
```

- Before every model call, the middleware queries the runtime with the latest user
  message (`type=TOOL`, `limit`) and adds the matches to the call, next to the agent's
  own tools. The model never sees the whole catalog.
- Routed tools are named `<server_id>_<tool>`; with `server_id="billing"`, the plain
  MCP names are used. A name that matches tools of several servers returns an error
  message to the model.
- Calls run through the runtime. Router errors and timeouts return as error tool
  messages, so the model can recover.
- The middleware is asynchronous: use `ainvoke` or `astream`, never `invoke`.
- Pair it with `RefreshPolicy(on_query_miss=True)` so that new tools are found.

## Composition

- Human approval for destructive tools: add
  `HumanInTheLoopMiddleware(interrupt_on={"issue_refund": True})` after the routing
  middleware, with a checkpointer. Use the routed name, such as
  `billing_issue_refund`, when the middleware is not scoped to one server.
- Put retries in the runtime, not in `ToolRetryMiddleware`, so that they are
  classified and counted by circuits.

## Deep Agents

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model=model, middleware=[CapabilityRoutingMiddleware(runtime, limit=5)]
)
```

## Multi-agent systems

Scope each agent to its servers with `CapabilityRoutingMiddleware(runtime,
server_id="crm")`, for example in a `langgraph_swarm.create_swarm` network with
`create_handoff_tool`. Use separate runtimes when agents belong to different trust
boundaries.

## Fixed tool sets

`await runtime.as_tool(capability_id, name=None)` returns a LangChain tool with the
MCP JSON schema, routed through the runtime, returning content and the structured
artifact. Use it for `model.bind_tools(...)` and LangGraph `ToolNode`.

## LangGraph workflows

Call the runtime from nodes for deterministic, auditable routing:

```python
async def route(state: State) -> dict[str, str]:
    [match] = await runtime.query(state.request, type=CapabilityType.TOOL, limit=1)
    return {"capability_id": match.capability_id}


async def act(state: State) -> dict[str, object]:
    message = await runtime.execute(state.capability_id, state.arguments)
    return {"result": message.artifact["structured_content"]}
```

`read_resource` and `get_prompt` work the same way for resources and prompts.
