"""Use the router inside a LangGraph workflow.

A three-step graph (route, act, report) retrieves the tool for a request, calls
it, and formats the answer. No model is involved, so every routing decision is
deterministic and auditable. Servers refresh on the first query that misses.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from common import billing_server, crm_server
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from mcp_capability_router import CapabilityType, MCPRuntime, RefreshPolicy


@dataclass
class Request:
    request: str
    arguments: dict[str, Any] = field(default_factory=dict)
    capability_id: str = ""
    result: Any = None
    answer: str = ""


def build_workflow(runtime: MCPRuntime) -> CompiledStateGraph[Request]:
    async def route(state: Request) -> dict[str, Any]:
        [match] = await runtime.query(state.request, type=CapabilityType.TOOL, limit=1)
        return {"capability_id": match.capability_id}

    async def act(state: Request) -> dict[str, Any]:
        message = await runtime.execute(state.capability_id, state.arguments)
        return {"result": message.artifact["structured_content"]["result"]}

    def report(state: Request) -> dict[str, Any]:
        return {"answer": f"{state.capability_id} -> {state.result}"}

    graph = StateGraph(Request)
    graph.add_node("route", route)
    graph.add_node("act", act)
    graph.add_node("report", report)
    graph.add_edge(START, "route")
    graph.add_edge("route", "act")
    graph.add_edge("act", "report")
    graph.add_edge("report", END)
    return graph.compile()


async def main() -> None:
    async with MCPRuntime() as runtime:
        policy = RefreshPolicy(on_query_miss=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        workflow = build_workflow(runtime)
        for request, arguments in (
            ("list the invoices of a customer", {"customer_id": "c-100"}),
            ("search customers by name", {"query": "glob"}),
        ):
            state = await workflow.ainvoke({"request": request, "arguments": arguments})
            print(state["answer"])


if __name__ == "__main__":
    asyncio.run(main())
