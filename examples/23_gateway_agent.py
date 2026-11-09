"""Give a LangChain agent the router through its MCP gateway.

Instead of the routing middleware, the agent connects to the gateway as to any
MCP server: `mcp_client_tools` turns the gateway's `search_tools` and
`call_tool` into LangChain tools, so the model searches the catalog itself and
calls what it finds. The same gateway serves any other MCP client unchanged.

Requires the `langchain` extra and a chat model, named as for
`langchain.chat_models.init_chat_model`:

    MCP_ROUTER_EXAMPLE_MODEL=openai:gpt-5.4-mini   # and OPENAI_API_KEY
"""

import asyncio
import os

from common import billing_server, crm_server, docs_server
from fastmcp import Client
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from mcp_capability_router import MCPRuntime, RefreshPolicy
from mcp_capability_router.integrations.langchain import mcp_client_tools

QUESTION = "Refund 100 of invoice inv-1."


async def main(model: BaseChatModel) -> None:
    async with MCPRuntime() as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)

        async with Client(runtime.as_mcp_server(max_results=3)) as client:
            agent = create_agent(
                model,
                tools=await mcp_client_tools(client),
                system_prompt=(
                    "You are a support assistant. Find tools with search_tools, "
                    "then call them with call_tool."
                ),
            )
            result = await agent.ainvoke({"messages": [{"role": "user", "content": QUESTION}]})
        for message in result["messages"]:
            if isinstance(message, ToolMessage):
                print(f"called {message.name}: {message.status}")
        answer = result["messages"][-1]
        if isinstance(answer, AIMessage):
            print(f"answer: {answer.text}")


if __name__ == "__main__":
    asyncio.run(main(init_chat_model(os.environ["MCP_ROUTER_EXAMPLE_MODEL"])))
