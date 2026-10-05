# LangChain and LangGraph agents

Agents choose tools better, faster, and more cheaply when they see a few relevant
tools instead of every tool of every server. The router gives LangChain agents the
tools that match each turn, and gives LangGraph workflows direct, resilient access to
every capability.

## Route tools with middleware

`CapabilityRoutingMiddleware` plugs into LangChain's `create_agent`. Before each model
call, it queries the runtime with the latest user message and adds the best matching
tools to the call, next to the tools the agent was created with. Tool calls run
through the runtime, so retries, circuit breakers, metrics, and health tracking apply.

![Agent routing](../assets/diagrams/agent-routing-light.png#only-light)
![Agent routing](../assets/diagrams/agent-routing-dark.png#only-dark)

```python
from langchain.agents import create_agent

from mcp_capability_router import CapabilityRoutingMiddleware, MCPRuntime, RefreshPolicy

async with MCPRuntime() as runtime:
    policy = RefreshPolicy(on_register=True, on_query_miss=True)
    await runtime.register_mcp("crm", "https://crm.example.com/mcp", refresh=policy)
    await runtime.register_mcp(
        "billing", "https://billing.example.com/mcp", refresh=policy
    )

    agent = create_agent(
        "openai:gpt-5.4-mini",
        tools=[],
        middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
        system_prompt="You are a support assistant. Use the tools to answer.",
    )
    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "Which invoices does Acme have?"}]}
    )
```

The middleware is asynchronous: invoke the agent with `ainvoke` or `astream`.

### Tool names

Routed tools are named `<server_id>_<tool>`, such as `billing_list_invoices`, so that
tools of different servers never collide. A middleware limited to one server with
`server_id="billing"` uses the plain MCP tool names. When a model calls a name that
matches tools of several servers, the call fails with an error message that the model
can act on.

### Failures

A routed tool that fails or times out returns an error tool message, such as
`ToolExecutionError: unknown customer`, instead of aborting the run, so the model can
correct its arguments or choose another tool.

### Choose the limit

`limit` bounds the routed tools per model call. Five to ten tools leave the model a
choice without flooding its context. Combine the middleware with
`RefreshPolicy(on_query_miss=True)` so that requests for tools added since the last
refresh still succeed.

## Combine with LangChain middleware

The routing middleware composes with LangChain's built-in middleware. For example,
require a human approval before a destructive tool runs:

```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from mcp_capability_router import CapabilityRoutingMiddleware

agent = create_agent(
    "openai:gpt-5.4-mini",
    tools=[],
    middleware=[
        CapabilityRoutingMiddleware(runtime, server_id="billing"),
        HumanInTheLoopMiddleware(interrupt_on={"issue_refund": True}),
    ],
    checkpointer=InMemorySaver(),
)
```

Retries belong in the runtime rather than in `ToolRetryMiddleware`: the runtime
retries only failures that can pass, and its circuit breakers count them.

## Deep Agents

[Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) build on
LangChain agents, so the same middleware routes MCP tools next to their planning and
file tools:

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="openai:gpt-5.4-mini",
    middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
    system_prompt="The crm_* and billing_* tools reach the company systems.",
)
```

## Multi-agent systems

Give each agent of a multi-agent system the tools of its own servers by scoping its
middleware with `server_id`. With
[langgraph-swarm](https://pypi.org/project/langgraph-swarm/):

```python
from langchain.agents import create_agent
from langgraph_swarm import create_handoff_tool, create_swarm

support = create_agent(
    "openai:gpt-5.4-mini",
    tools=[create_handoff_tool(agent_name="billing")],
    middleware=[CapabilityRoutingMiddleware(runtime, server_id="crm")],
    name="support",
)
billing = create_agent(
    "openai:gpt-5.4-mini",
    tools=[create_handoff_tool(agent_name="support")],
    middleware=[CapabilityRoutingMiddleware(runtime, server_id="billing")],
    name="billing",
)
swarm = create_swarm([support, billing], default_active_agent="support").compile()
```

## LangChain tools

`as_tool` returns a LangChain tool for one MCP tool. It uses the tool's JSON schema,
runs through the runtime, and returns the content of the result with the structured
content as its artifact. Use it when the set of tools is fixed, such as for a
LangGraph `ToolNode`:

```python
from langgraph.prebuilt import ToolNode

from mcp_capability_router import CapabilityType

matches = await runtime.retrieve("invoices", type=CapabilityType.TOOL, limit=5)
tools = [await runtime.as_tool(match.capability_id) for match in matches]
tool_node = ToolNode(tools)
model_with_tools = model.bind_tools(tools)
```

## LangGraph workflows

In a deterministic workflow, call the runtime from the nodes. Every routing decision
is then explicit and auditable:

```python
from langgraph.graph import END, START, StateGraph


async def route(state: Request) -> dict[str, str]:
    [match] = await runtime.query(state.request, type=CapabilityType.TOOL, limit=1)
    return {"capability_id": match.capability_id}


async def act(state: Request) -> dict[str, object]:
    message = await runtime.execute(state.capability_id, state.arguments)
    return {"result": message.artifact["structured_content"]}


graph = StateGraph(Request)
graph.add_node("route", route)
graph.add_node("act", act)
graph.add_edge(START, "route")
graph.add_edge("route", "act")
graph.add_edge("act", END)
workflow = graph.compile()
```

Resources and prompts work the same way, with `read_resource` and `get_prompt`. The
[examples](../examples.md) include complete programs for every integration above.
