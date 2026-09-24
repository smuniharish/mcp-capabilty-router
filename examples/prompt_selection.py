"""Example C: LangChain-style Prompt-only capability selection.

Run:
    uv run python -m examples.prompt_selection

Credential-free: a single in-process adapter exposes only Prompts. Demonstrates that
prompt discovery/retrieval/selection works completely independently of Tools and
Resources, per the "first-class capability" requirement.
"""

from __future__ import annotations

import asyncio

from mcp_capability_router import CapabilityType, MCPRuntime


class PromptLibraryAdapter:
    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return []

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return [
            {
                "name": "summarize_ticket",
                "description": "summarize a support ticket for a human agent",
                "arguments": [{"name": "ticket_id"}],
            },
            {
                "name": "draft_reply",
                "description": "draft a customer reply for a support ticket",
                "arguments": [{"name": "ticket_id"}, {"name": "tone"}],
            },
        ]

    async def call_tool(self, name, arguments=None):
        raise NotImplementedError

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        arguments = arguments or {}
        if name == "draft_reply":
            return {
                "instructions": (
                    f"Draft a {arguments.get('tone', 'neutral')} reply for "
                    f"ticket {arguments.get('ticket_id')}."
                )
            }
        return {"instructions": f"Summarize ticket {arguments.get('ticket_id')}."}


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_server("prompts", lambda: PromptLibraryAdapter())
        await runtime.refresh_server("prompts")

        assert await runtime.retrieve("anything", type=CapabilityType.TOOL) == []
        assert await runtime.retrieve("anything", type=CapabilityType.RESOURCE) == []

        matches = await runtime.retrieve("draft a reply", type=CapabilityType.PROMPT)
        selected = matches[0]
        print("selected prompt:", selected.name)
        rendered = await runtime.get_prompt(
            selected.capability_id, {"ticket_id": "T-42", "tone": "empathetic"}
        )
        print("rendered:", rendered["instructions"])


if __name__ == "__main__":
    asyncio.run(main())
