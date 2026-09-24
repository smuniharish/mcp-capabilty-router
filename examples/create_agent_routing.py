"""LangChain ``create_agent`` integration boundary.

Install with ``uv sync --extra mcp --extra agents --extra openai --extra examples`` and
provide a LangChain-compatible chat model. This example instantiates ``ChatOpenAI``
directly with the values your application already manages (see ``.env.example``); no
provider-abstraction layer is required. Any LangChain chat model class works the same way
(``ChatLiteLLM``, ``ChatAnthropic``, ...).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import MCPRuntime


async def main() -> None:
    try:
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise SystemExit(
            "Install optional agent dependencies first: "
            "uv sync --extra agents --extra openai --extra examples"
        ) from exc

    load_dotenv()
    api_key = os.environ.get("EXPLABS_API_KEY")
    if not api_key:
        raise SystemExit("Set EXPLABS_API_KEY in .env before running this example.")

    # Direct LangChain model instantiation - the router never wraps or configures models.
    model = ChatOpenAI(
        model=os.environ.get("EXPLABS_MODEL", "gpt-5.6-luna"),
        base_url=os.environ.get("EXPLABS_BASE_URL", "https://api.experientiallabs.ai/v1"),
        api_key=api_key,
    )
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "router-note.txt").write_text("real MCP agent", encoding="utf-8")
        async with MCPRuntime() as runtime:
            client = MultiServerMCPClient(
                {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(root)],
                        "transport": "stdio",
                    }
                }
            )
            await runtime.register_mcp_client("filesystem", client)
            await runtime.refresh_server("filesystem")
            selected = await runtime.retrieve("read file", limit=1)
            capability_id = selected[0].capability_id

            async def selected_tool(**arguments):
                return await runtime.execute(capability_id, arguments)

            tool = StructuredTool.from_function(
                coroutine=selected_tool,
                name=selected[0].name,
                description=selected[0].description or "Selected MCP capability",
                args_schema=selected[0].schema,
            )
            agent = create_agent(model=model, tools=[tool])
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "Read router-note.txt"}]}
            )
            print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
