"""Multi-agent LangGraph network using capability routing.

Run:
    uv run python examples/langgraph_network.py

This example is credential-free. Replace the node bodies with application-owned model calls
after installing the ``openai`` extra; the graph and routing boundaries stay the same.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph

from mcp_capability_router import MCPRuntime


@dataclass
class NetworkState:
    request: str
    capability_id: str = ""
    research: str = ""
    answer: str = ""


async def build_graph(runtime: MCPRuntime):
    async def router(state: NetworkState) -> dict[str, str]:
        matches = await runtime.query(state.request, refresh_servers=["filesystem"], limit=1)
        return {"capability_id": matches[0].capability_id}

    async def researcher(state: NetworkState) -> dict[str, str]:
        result = await runtime.execute(state.capability_id, {"path": "router-note.txt"})
        return {"research": str(result)}

    async def writer(state: NetworkState) -> dict[str, str]:
        return {"answer": f"writer received: {state.research}"}

    graph = StateGraph(NetworkState)
    graph.add_node("router", router)
    graph.add_node("researcher", researcher)
    graph.add_node("writer", writer)
    graph.add_edge(START, "router")
    graph.add_edge("router", "researcher")
    graph.add_edge("researcher", "writer")
    graph.add_edge("writer", END)
    return graph.compile()


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "router-note.txt").write_text("real MCP graph", encoding="utf-8")
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
            graph = await build_graph(runtime)
            result = await graph.ainvoke({"request": "read file"})
            print(result["answer"])


if __name__ == "__main__":
    asyncio.run(main())
