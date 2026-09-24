"""Example B: LangChain-style Resource-only capability selection.

Run:
    uv run python -m examples.resource_selection

Credential-free: a single in-process adapter exposes only Resources. Demonstrates that
resource discovery/retrieval/selection works completely independently of Tools and
Prompts, per the "first-class capability" requirement.
"""

from __future__ import annotations

import asyncio

from mcp_capability_router import CapabilityType, MCPRuntime


class KnowledgeBaseAdapter:
    def __init__(self) -> None:
        self._documents = {
            "file:///onboarding.md": "New hires should complete security training in week one.",
            "file:///benefits.md": "Health benefits enroll within 30 days of the start date.",
        }

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return []

    async def list_resources(self):
        return [
            {
                "uri": "file:///onboarding.md",
                "name": "onboarding",
                "description": "onboarding guide",
            },
            {"uri": "file:///benefits.md", "name": "benefits", "description": "benefits guide"},
        ]

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        raise NotImplementedError

    async def read_resource(self, uri):
        return self._documents[uri]

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_server("kb", lambda: KnowledgeBaseAdapter())
        await runtime.refresh_server("kb")

        # Only Resources exist on this server; Tool/Prompt retrieval must stay empty.
        assert await runtime.retrieve("anything", type=CapabilityType.TOOL) == []
        assert await runtime.retrieve("anything", type=CapabilityType.PROMPT) == []

        matches = await runtime.retrieve("benefits", type=CapabilityType.RESOURCE)
        selected = matches[0]
        print("selected resource:", selected.name)
        print("content:", await runtime.read_resource(selected.capability_id))


if __name__ == "__main__":
    asyncio.run(main())
