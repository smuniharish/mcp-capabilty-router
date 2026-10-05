"""Give a LangChain agent only the MCP tools that each turn needs.

`CapabilityRoutingMiddleware` retrieves the tools that match the latest user
message and adds them to the model call; the agent starts without any tools.
Tool calls run through the runtime's resilience pipeline.

Requires a chat model, named as for `langchain.chat_models.init_chat_model`:

    MCP_ROUTER_EXAMPLE_MODEL=openai:gpt-5.4-mini   # and OPENAI_API_KEY
"""

import asyncio
import os

from common import billing_server, crm_server, docs_server
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from mcp_capability_router import CapabilityRoutingMiddleware, MCPRuntime, RefreshPolicy

QUESTION = "Which invoices does customer c-100 have?"


async def main(model: BaseChatModel) -> None:
    async with MCPRuntime() as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)

        agent = create_agent(
            model,
            tools=[],
            middleware=[CapabilityRoutingMiddleware(runtime, limit=3)],
            system_prompt="You are a support assistant. Use the tools to answer.",
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": QUESTION}]}
        )
        for message in result["messages"]:
            if isinstance(message, ToolMessage):
                print(f"called {message.name}: {message.status}")
        answer = result["messages"][-1]
        if isinstance(answer, AIMessage):
            print(f"answer: {answer.text}")


if __name__ == "__main__":
    asyncio.run(main(init_chat_model(os.environ["MCP_ROUTER_EXAMPLE_MODEL"])))
