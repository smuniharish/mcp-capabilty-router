"""Real Playwright MCP + langgraph-swarm network.

Install:
    uv sync --extra mcp --extra agents --extra openai --extra swarm --extra examples

Run after setting EXPLABS_API_KEY in .env:
    uv run python -m examples.langgraph_swarm_network
"""

from __future__ import annotations

import asyncio
import os

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import MCPRuntime


async def main() -> None:
    try:
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI
        from langgraph.checkpoint.memory import InMemorySaver
        from langgraph_swarm import create_handoff_tool, create_swarm
    except ImportError as exc:
        raise SystemExit(
            "Install swarm dependencies: "
            "uv sync --extra mcp --extra agents --extra openai --extra swarm --extra examples"
        ) from exc

    load_dotenv()
    api_key = os.environ.get("EXPLABS_API_KEY")
    if not api_key:
        raise SystemExit("Set EXPLABS_API_KEY in .env before running this example.")
    model = ChatOpenAI(
        model=os.environ.get("EXPLABS_MODEL", "gpt-5.6-luna"),
        base_url=os.environ.get("EXPLABS_BASE_URL", "https://api.experientiallabs.ai/v1"),
        api_key=api_key,
    )

    async with MCPRuntime() as runtime:
        client = MultiServerMCPClient(
            {
                "playwright": {
                    "command": "npx",
                    "args": ["-y", "@playwright/mcp@latest"],
                    "transport": "stdio",
                }
            }
        )
        await runtime.register_mcp_client(
            "playwright",
            client,
            client_server_name="playwright",
        )
        await runtime.refresh_server("playwright")
        candidates = await runtime.retrieve("navigate", limit=20)
        selected = next((item for item in candidates if item.name == "browser_navigate"), None)
        if selected is None:
            raise RuntimeError("Playwright MCP did not expose browser_navigate")

        async def navigate(**arguments):
            return await runtime.execute(selected.capability_id, arguments)

        browser_tool = StructuredTool.from_function(
            coroutine=navigate,
            name=selected.name,
            description=selected.description,
            args_schema=selected.schema,
        )
        navigator = create_agent(
            model,
            tools=[
                browser_tool,
                create_handoff_tool(
                    agent_name="auditor", description="Ask the auditor to review the page."
                ),
            ],
            system_prompt="Navigate to the requested page, then hand off for review.",
            name="navigator",
        )
        auditor = create_agent(
            model,
            tools=[create_handoff_tool(agent_name="navigator")],
            system_prompt="Review the navigator's result and summarize it.",
            name="auditor",
        )
        workflow = create_swarm(
            [navigator, auditor],
            default_active_agent="navigator",
        ).compile(checkpointer=InMemorySaver())
        result = await workflow.ainvoke(
            {"messages": [{"role": "user", "content": "Open https://example.com and review it."}]},
            {"configurable": {"thread_id": "playwright-swarm-demo"}},
        )
        print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
