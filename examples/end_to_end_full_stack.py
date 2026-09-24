"""Example T: Full end-to-end capability-routing workflow, in one place.

Run:
    uv run python -m examples.end_to_end_full_stack

Credential-free. This is the single "everything at once" example: it exercises, in one
run, every major concern the architecture describes rather than one concern at a time
(as the other, more focused example files do):

* Tools + Resources + Prompts together, as first-class capabilities.
* Static registration (a support-desk server available from the start) *and* dynamic
  registration (an escalation server registered mid-run, based on a tool result).
* Query-driven refresh (only refreshing servers relevant to the current query).
* Retrieval -> ranking -> JIT loading of only the capabilities actually selected.
* Resilience: a transient failure recovered by retry, and a persistently failing
  server whose health degrades without taking the whole workflow down.
* A LangGraph graph tying the above into one small support-ticket workflow.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from langgraph.graph import END, START, StateGraph
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

from mcp_capability_router import CapabilityType, MCPRuntime
from mcp_capability_router.resilience import semantic_classifier


class SupportDeskAdapter:
    """Statically registered from the start: the common-case ticket tools."""

    def __init__(self) -> None:
        self._policy_doc = "Refunds are approved automatically for orders under $50."
        self.attempts = 0

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [
            {"name": "classify_ticket", "description": "classify a support ticket's severity"},
            {"name": "lookup_order", "description": "look up an order, flaky on first call"},
        ]

    async def list_resources(self):
        return [
            {
                "uri": "file:///refund_policy.txt",
                "name": "refund_policy",
                "description": "refund policy reference",
            }
        ]

    async def list_prompts(self):
        return [
            {
                "name": "draft_customer_reply",
                "description": "draft a reply to the customer",
                "arguments": [{"name": "ticket_id"}],
            }
        ]

    async def call_tool(self, name, arguments=None):
        if name == "classify_ticket":
            text = (arguments or {}).get("text", "")
            severity = "high" if "urgent" in text or "escalat" in text else "normal"
            return {"severity": severity}
        if name == "lookup_order":
            self.attempts += 1
            if self.attempts == 1:
                raise TimeoutError("order service momentarily unavailable")
            return {"order_id": (arguments or {}).get("order_id"), "amount": 42}
        raise NotImplementedError

    async def read_resource(self, uri):
        return self._policy_doc

    async def get_prompt(self, name, arguments=None):
        return {"instructions": f"Draft a reply for ticket {(arguments or {}).get('ticket_id')}."}


class EscalationAdapter:
    """Only registered when a ticket is actually classified as high severity."""

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "notify_on_call", "description": "page the on-call engineer"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"paged": True}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


@dataclass
class TicketState:
    ticket_id: str
    text: str
    order_id: str
    severity: str = ""
    order_amount: int = 0
    policy_reference: str = ""
    reply: str = ""
    escalated: bool = False


async def build_graph(runtime: MCPRuntime):
    async def classify_node(state: TicketState) -> dict:
        matches = await runtime.query("classify_ticket", refresh_servers=["support_desk"])
        result = await runtime.execute(matches[0].capability_id, {"text": state.text})
        return {"severity": result["severity"]}

    async def gather_context_node(state: TicketState) -> dict:
        order_capability = (await runtime.retrieve("lookup_order", type=CapabilityType.TOOL))[0]
        # Retry (a tenacity.AsyncRetrying with stop_after_attempt(2) on this runtime)
        # transparently absorbs the adapter's first-call failure; the graph node
        # itself has no retry logic of its own.
        order = await runtime.execute(order_capability.capability_id, {"order_id": state.order_id})

        policy_capability = (await runtime.retrieve("refund_policy", type=CapabilityType.RESOURCE))[
            0
        ]
        # JIT loading materializes the resource handle before it's read, mirroring how
        # a Tool would be JIT-loaded before being bound into an agent's toolset.
        await runtime.load(policy_capability.capability_id)
        policy_text = await runtime.read_resource(policy_capability.capability_id)
        return {"order_amount": order["amount"], "policy_reference": policy_text}

    async def escalate_node(state: TicketState) -> dict:
        if state.severity != "high":
            return {"escalated": False}
        # Dynamic registration mid-graph-run: the escalation server only needs to exist
        # once a ticket is actually classified as high severity.
        await runtime.register_server("escalation", lambda: EscalationAdapter())
        await runtime.refresh_server("escalation")
        capability = (await runtime.retrieve("notify_on_call", server_id="escalation"))[0]
        await runtime.execute(capability.capability_id)
        return {"escalated": True}

    async def reply_node(state: TicketState) -> dict:
        prompt_capability = (
            await runtime.retrieve("draft_customer_reply", type=CapabilityType.PROMPT)
        )[0]
        rendered = await runtime.get_prompt(
            prompt_capability.capability_id, {"ticket_id": state.ticket_id}
        )
        suffix = " Escalated to on-call." if state.escalated else ""
        return {"reply": f"{rendered['instructions']} {state.policy_reference}{suffix}"}

    graph = StateGraph(TicketState)
    graph.add_node("classify", classify_node)
    graph.add_node("gather_context", gather_context_node)
    graph.add_node("escalate", escalate_node)
    graph.add_node("reply", reply_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", "gather_context")
    graph.add_edge("gather_context", "escalate")
    graph.add_edge("escalate", "reply")
    graph.add_edge("reply", END)
    return graph.compile()


async def main() -> None:
    retry = AsyncRetrying(
        stop=stop_after_attempt(2),
        retry=retry_if_exception(semantic_classifier),
        reraise=True,
    )
    async with MCPRuntime(retry=retry) as runtime:
        await runtime.register_server("support_desk", lambda: SupportDeskAdapter())
        graph = await build_graph(runtime)

        result = await graph.ainvoke(
            {
                "ticket_id": "T-901",
                "text": "customer requesting urgent escalation for a failed refund",
                "order_id": "O-77",
            }
        )
        print("severity:", result["severity"])
        print("escalated:", result["escalated"])
        print("reply:", result["reply"])
        print("support_desk health:", await runtime.health("support_desk"))


if __name__ == "__main__":
    asyncio.run(main())
