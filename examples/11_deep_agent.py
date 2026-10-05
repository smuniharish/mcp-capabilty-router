"""Route MCP tools into a DeepAgents agent.

DeepAgents builds on LangChain agents, so the same `CapabilityRoutingMiddleware`
adds the relevant MCP tools to each turn, next to DeepAgents' own planning and
file tools.

Requires a chat model, named as for `langchain.chat_models.init_chat_model`:

    MCP_ROUTER_EXAMPLE_MODEL=openai:gpt-5.4-mini   # and OPENAI_API_KEY
"""

import asyncio
import os

from common import billing_server, crm_server
from deepagents import create_deep_agent
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage

from mcp_capability_router import CapabilityRoutingMiddleware, MCPRuntime, RefreshPolicy

QUESTION = "Find the customer Globex and list its invoices."


async def main(model: BaseChatModel) -> None:
    async with MCPRuntime() as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)

        agent = create_deep_agent(
            model=model,
            middleware=[CapabilityRoutingMiddleware(runtime, limit=4)],
            system_prompt=(
                "You are a support assistant. The crm_* and billing_* tools reach "
                "the company systems; use them to answer."
            ),
        )
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": QUESTION}]}
        )
        routed = [
            message.name
            for message in result["messages"]
            if isinstance(message, ToolMessage)
            and str(message.name).startswith(("crm_", "billing_"))
        ]
        print(f"routed tools called: {routed}")
        answer = result["messages"][-1]
        if isinstance(answer, AIMessage):
            print(f"answer: {answer.text}")


if __name__ == "__main__":
    asyncio.run(main(init_chat_model(os.environ["MCP_ROUTER_EXAMPLE_MODEL"])))
