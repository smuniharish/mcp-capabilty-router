"""Example S: LangGraph node that dynamically registers a new MCP server mid-run.

Run:
    uv run python -m examples.langgraph_dynamic_discovery

Credential-free: a "directory" node asks a directory-style adapter which downstream
server handles a request, registers that server with the runtime *during* the graph
run (not at startup), refreshes it, and only then routes to a node that uses it. This
demonstrates LangGraph driving dynamic MCP server registration, distinct from
``dynamic_registration.py`` (same underlying pattern, without LangGraph) and from
``langgraph_network.py`` (statically registered filesystem server).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from langgraph.graph import END, START, StateGraph

from mcp_capability_router import MCPRuntime


@dataclass
class DiscoveryState:
    request: str
    server_id: str = ""
    capability_id: str = ""
    result: str = ""
    registered_servers: list[str] = field(default_factory=list)


class DirectoryAdapter:
    """Reports which downstream MCP server should handle a given kind of request."""

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "route_request", "description": "pick a downstream MCP server"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        request = (arguments or {}).get("request", "")
        if "billing" in request:
            return {"server_id": "billing", "prefix": "billing"}
        return {"server_id": "reports", "prefix": "reports"}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


class DownstreamAdapter:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": f"{self.prefix}_handle", "description": f"handle a {self.prefix} request"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"handled_by": self.prefix}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def build_graph(runtime: MCPRuntime):
    async def directory_node(state: DiscoveryState) -> dict:
        matches = await runtime.retrieve("route_request")
        decision = await runtime.execute(matches[0].capability_id, {"request": state.request})
        return {"server_id": decision["server_id"]}

    async def register_node(state: DiscoveryState) -> dict:
        # Registration happens *inside the graph run*, driven by the directory node's
        # decision -- not pre-configured before the graph started.
        if state.server_id not in state.registered_servers:
            adapter = DownstreamAdapter(state.server_id)
            await runtime.register_server(state.server_id, lambda adapter=adapter: adapter)
            await runtime.refresh_server(state.server_id)
        return {"registered_servers": [*state.registered_servers, state.server_id]}

    async def handle_node(state: DiscoveryState) -> dict:
        matches = await runtime.retrieve("handle", server_id=state.server_id)
        result = await runtime.execute(matches[0].capability_id)
        return {"result": result["handled_by"]}

    graph = StateGraph(DiscoveryState)
    graph.add_node("directory", directory_node)
    graph.add_node("register", register_node)
    graph.add_node("handle", handle_node)
    graph.add_edge(START, "directory")
    graph.add_edge("directory", "register")
    graph.add_edge("register", "handle")
    graph.add_edge("handle", END)
    return graph.compile()


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_server("directory", lambda: DirectoryAdapter())
        await runtime.refresh_server("directory")
        graph = await build_graph(runtime)

        for request in ("please process a billing refund", "generate a quarterly report"):
            result = await graph.ainvoke({"request": request})
            print(
                f"{request!r} -> routed to {result['server_id']!r}, handled_by={result['result']!r}"
            )


if __name__ == "__main__":
    asyncio.run(main())
