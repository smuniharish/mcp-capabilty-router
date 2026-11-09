"""Route MCP tools for any framework: here, the plain OpenAI SDK.

The core needs no agent framework. `MCPRuntime.route_tools` returns the
`RoutedTool`s that match a request: each has a name, a description, and the JSON
schema of its arguments, which is all a model needs, and calling it runs the
MCP tool through the runtime. This example shows them to a model with the
OpenAI Chat Completions API and runs the calls it asks for. Any framework that
accepts JSON-schema tools works the same way.

Requires the `openai` package and an OpenAI-compatible endpoint:

    MCP_ROUTER_EXAMPLE_OPENAI_MODEL=gpt-5.4-mini   # and OPENAI_API_KEY, optionally OPENAI_BASE_URL
"""

import asyncio
import json
import os
from typing import Any

from common import billing_server, crm_server, docs_server
from mcp import types
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionFunctionToolParam

from mcp_capability_router import MCPCapabilityRouterError, MCPRuntime, RefreshPolicy, RoutedTool

QUESTION = "Find the customer Globex and tell me which of their invoices are open."


def definition(tool: RoutedTool) -> ChatCompletionFunctionToolParam:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.input_schema),
        },
    }


async def run(tool: RoutedTool, arguments: str) -> str:
    try:
        result = await tool(json.loads(arguments or "{}"))
    except MCPCapabilityRouterError as error:
        return f"error: {error}"
    if result.structured_content is not None:
        return json.dumps(result.structured_content)
    return "\n".join(block.text for block in result.content if isinstance(block, types.TextContent))


async def main(client: AsyncOpenAI, model: str) -> None:
    async with MCPRuntime() as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)

        tools = {tool.name: tool for tool in await runtime.route_tools(QUESTION, limit=3)}
        print(f"routed tools: {sorted(tools)}")
        messages: list[Any] = [
            {"role": "system", "content": "You are a support assistant. Use the tools."},
            {"role": "user", "content": QUESTION},
        ]
        for _ in range(6):
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=[definition(tool) for tool in tools.values()],
            )
            reply = response.choices[0].message
            messages.append(reply.model_dump(exclude_none=True))
            if not reply.tool_calls:
                print(f"answer: {reply.content}")
                return
            for call in reply.tool_calls:
                if call.type != "function":
                    continue
                tool = tools.get(call.function.name)
                content = (
                    await run(tool, call.function.arguments)
                    if tool is not None
                    else f"error: no tool named {call.function.name!r}"
                )
                print(f"called {call.function.name}")
                messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        print("no answer after six model calls")


if __name__ == "__main__":
    asyncio.run(main(AsyncOpenAI(), os.environ["MCP_ROUTER_EXAMPLE_OPENAI_MODEL"]))
