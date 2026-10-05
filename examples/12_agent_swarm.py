"""Hand off between agents that each see only their own server's tools.

Two LangChain agents form a langgraph-swarm network: a support agent scoped to
the CRM server and a billing agent scoped to the billing server. Each agent's
middleware routes only the tools of its own server, and handoff tools pass the
conversation between them.

Requires a chat model, named as for `langchain.chat_models.init_chat_model`:

    MCP_ROUTER_EXAMPLE_MODEL=openai:gpt-5.4-mini   # and OPENAI_API_KEY
"""

import asyncio
import os

from common import billing_server, crm_server
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langgraph_swarm import create_handoff_tool, create_swarm

from mcp_capability_router import CapabilityRoutingMiddleware, MCPRuntime, RefreshPolicy

QUESTION = "Look up Acme Corp, then refund 100 of invoice inv-1."


async def main(model: BaseChatModel) -> None:
    async with MCPRuntime() as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)

        support = create_agent(
            model,
            tools=[create_handoff_tool(agent_name="billing")],
            middleware=[CapabilityRoutingMiddleware(runtime, server_id="crm")],
            system_prompt="You handle customer records. Hand billing work to billing.",
            name="support",
        )
        billing = create_agent(
            model,
            tools=[create_handoff_tool(agent_name="support")],
            middleware=[CapabilityRoutingMiddleware(runtime, server_id="billing")],
            system_prompt="You handle invoices and refunds.",
            name="billing",
        )
        swarm = create_swarm([support, billing], default_active_agent="support")
        result = await swarm.compile().ainvoke(
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
