# Agent frameworks

Agents choose tools better, faster, and more cheaply when they see a few relevant
tools instead of every tool of every server. The core of the router needs no agent
framework: `route_tools` gives any framework the tools that match a request, and
the [MCP gateway](gateway.md) serves the router to any MCP client. Dedicated
integrations live in `mcp_capability_router.integrations.<framework>`, behind an
extra of the same name.

![Agent routing](../assets/diagrams/agent-routing-light.png#only-light)
![Agent routing](../assets/diagrams/agent-routing-dark.png#only-dark)

## Any framework: route tools

`route_tools` ranks the tools against a request and returns `RoutedTool`s. Each has a
`name`, a `description`, and the JSON schema of its arguments in `input_schema`,
which is all a model needs. Awaiting it with the arguments runs the MCP tool through
the runtime, so retries, circuit breakers, interceptors, caching, and metrics apply,
and returns FastMCP's `CallToolResult`.

```python
import json

from openai import AsyncOpenAI

from mcp_capability_router import MCPCapabilityRouterError, MCPRuntime

openai = AsyncOpenAI()


async def answer(runtime: MCPRuntime, question: str) -> str | None:
    tools = await runtime.route_tools(question, limit=5)
    messages = [{"role": "user", "content": question}]
    response = await openai.chat.completions.create(
        model="gpt-5.4-mini",
        messages=messages,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in tools
        ],
    )
    message = response.choices[0].message
    messages.append(message.model_dump(exclude_none=True))
    for call in message.tool_calls or []:
        try:
            tool = await runtime.resolve_tool(call.function.name)
            result = await tool(json.loads(call.function.arguments))
            content = json.dumps(result.structured_content)
        except MCPCapabilityRouterError as error:
            content = f"{type(error).__name__}: {error}"
        messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
    ...
```

- Routed tools are named `<server_id>_<tool>`, such as `billing_list_invoices`, so
  that tools of different servers never collide. With `server_id="billing"`, they
  keep the plain MCP tool names.
- `resolve_tool` maps a name that a model called back to its tool, including tools
  routed on an earlier turn. A name that matches tools of several servers raises
  `InvalidRequestError`, which the model can act on.
- `where` filters candidates, for example `where=lambda tool: not tool.destructive`.
  It is not an authorization check: protect execution with an
  [interceptor](security.md#restrict-tools) as well.
- `limit` bounds the tools per model call. Five to ten tools leave the model a
  choice without flooding its context. Combine it with
  `RefreshPolicy(on_query_miss=True)` so that requests for tools added since the last
  refresh still succeed.
- `await runtime.tool(capability_id)` returns one fixed `RoutedTool`.

Agno, CrewAI, the OpenAI Agents SDK, and other frameworks take the same three
fields; convert `RoutedTool`s to their tool type in a few lines, or connect them to
the [gateway](gateway.md) if they speak MCP.

## LangChain

Install the `langchain` extra:

```bash
pip install "mcp-capability-router[langchain]"
```

### Route tools with middleware

`CapabilityRoutingMiddleware` plugs into LangChain's `create_agent`. Before each model
call, it routes tools with the latest user message and adds them to the call, next to
the tools the agent was created with. Tool calls run through the runtime.

```python
from langchain.agents import create_agent

from mcp_capability_router import MCPRuntime, RefreshPolicy
from mcp_capability_router.integrations.langchain import CapabilityRoutingMiddleware

async with MCPRuntime() as runtime:
    policy = RefreshPolicy(on_register=True, on_query_miss=True)
    await runtime.register_mcp("crm", "https://crm.example.com/mcp", refresh=policy)
    await runtime.register_mcp("billing", "https://billing.example.com/mcp", refresh=policy)

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

The middleware is asynchronous: invoke the agent with `ainvoke` or `astream`. A
routed tool that fails or times out returns an error tool message, such as
`ToolExecutionError: unknown customer`, instead of aborting the run, so the model can
correct its arguments or choose another tool.

### Combine with LangChain middleware

The routing middleware composes with LangChain's built-in middleware. For example,
require a human approval before a destructive tool runs:

```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from mcp_capability_router.integrations.langchain import CapabilityRoutingMiddleware

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

### Deep Agents

[Deep Agents](https://docs.langchain.com/oss/python/deepagents/overview) build on
LangChain agents, so the same middleware routes MCP tools next to their planning and
file tools:

```python
from deepagents import create_deep_agent

from mcp_capability_router.integrations.langchain import CapabilityRoutingMiddleware

agent = create_deep_agent(
    model="openai:gpt-5.4-mini",
    middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
    system_prompt="The crm_* and billing_* tools reach the company systems.",
)
```

### Multi-agent systems

Give each agent of a multi-agent system the tools of its own servers by scoping its
middleware with `server_id`. With
[langgraph-swarm](https://pypi.org/project/langgraph-swarm/):

```python
from langchain.agents import create_agent
from langgraph_swarm import create_handoff_tool, create_swarm

from mcp_capability_router.integrations.langchain import CapabilityRoutingMiddleware

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

### LangChain tools

`to_langchain_tool` turns a `RoutedTool` into a LangChain `StructuredTool`. Use it
when the set of tools is fixed, such as for a LangGraph `ToolNode`:

```python
from langgraph.prebuilt import ToolNode

from mcp_capability_router.integrations.langchain import to_langchain_tool

tools = [to_langchain_tool(tool) for tool in await runtime.route_tools("invoices")]
tool_node = ToolNode(tools)
model_with_tools = model.bind_tools(tools)
```

`mcp_client_tools(client)` turns the tools of any connected FastMCP `Client`, such as
one connected to the [gateway](gateway.md), into LangChain tools.

### Embeddings and vector stores

`LangChainEmbedder` lets [`QdrantRetriever`](retrieval.md) rank with any LangChain
embedding model. `VectorStoreRetriever` ranks with any LangChain `VectorStore`
instead, with an optional document compressor as a reranker. See
[Retrieval](retrieval.md#langchain-vector-stores).

## LangGraph workflows

In a deterministic workflow, call the runtime from the nodes. Every routing decision
is then explicit and auditable:

```python
from langgraph.graph import END, START, StateGraph

from mcp_capability_router import CapabilityType


async def route(state: Request) -> dict[str, str]:
    [match] = await runtime.query(state.request, type=CapabilityType.TOOL, limit=1)
    return {"capability_id": match.capability_id}


async def act(state: Request) -> dict[str, object]:
    result = await runtime.execute(state.capability_id, state.arguments)
    return {"result": result.data}


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

## Add an integration

An integration converts `RoutedTool`s to the framework's tool type and, where the
framework has a hook before each model call, routes tools there. It lives in
`mcp_capability_router.integrations.<framework>`, imports the framework only there,
and declares the framework in an extra of the same name.