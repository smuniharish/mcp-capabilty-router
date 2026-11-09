"""A LangChain agent that calls MCP tools through the routing middleware."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage

from mcp_capability_router import MCPRuntime, RefreshPolicy
from mcp_capability_router.integrations.langchain import CapabilityRoutingMiddleware
from tests.langchain_support import ScriptedChatModel, tool_messages
from tests.support import demo_server


async def test_agent_calls_mcp_tools_through_the_middleware() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_mcp("demo", demo_server(), refresh=RefreshPolicy(on_register=True))
        model = ScriptedChatModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "add",
                            "args": {"a": 2, "b": 3},
                            "id": "call-1",
                            "type": "tool_call",
                        },
                        {
                            "name": "fail",
                            "args": {"reason": "out of stock"},
                            "id": "call-2",
                            "type": "tool_call",
                        },
                    ],
                ),
                AIMessage(content="The sum is 5."),
            ]
        )
        agent = create_agent(
            model,
            tools=[],
            middleware=[CapabilityRoutingMiddleware(runtime, server_id="demo")],
        )
        result = await agent.ainvoke({"messages": [HumanMessage("add two numbers, or fail")]})
        assert model.calls[0] == ["add", "fail"]
        added, failed = tool_messages(result)
        assert added.artifact == {"result": 5}
        assert failed.status == "error"
        assert "out of stock" in str(failed.content)
