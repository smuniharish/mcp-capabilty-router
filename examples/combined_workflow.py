"""Combined Tool + Resource + Prompt workflow.

Run:
    uv run python -m examples.combined_workflow

This example is credential-free: it uses a single in-process adapter exposing all
three capability types, then chains a prompt, a tool call, and a resource read into
one answer through the same runtime.
"""

from __future__ import annotations

import asyncio

from mcp_capability_router import CapabilityType, MCPRuntime


class WorkspaceAdapter:
    def __init__(self) -> None:
        self._documents = {"reference.txt": "quarterly revenue rose 12%"}

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "fetch_metrics", "description": "fetch the latest business metrics"}]

    async def list_resources(self):
        return [
            {
                "uri": "file:///reference.txt",
                "name": "reference",
                "description": "background reference material",
            }
        ]

    async def list_prompts(self):
        return [
            {
                "name": "summarize",
                "description": "summarize metrics using reference material",
                "arguments": [{"name": "audience"}],
            }
        ]

    async def call_tool(self, name, arguments=None):
        return {"revenue_growth": "12%"}

    async def read_resource(self, uri):
        return self._documents["reference.txt"]

    async def get_prompt(self, name, arguments=None):
        audience = (arguments or {}).get("audience", "general")
        return {"instructions": f"Summarize the metrics for a {audience} audience."}


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_server("workspace", lambda: WorkspaceAdapter())
        await runtime.refresh_server("workspace")

        prompt = (await runtime.retrieve("summarize", type=CapabilityType.PROMPT))[0]
        tool = (await runtime.retrieve("metrics", type=CapabilityType.TOOL))[0]
        resource = (await runtime.retrieve("reference", type=CapabilityType.RESOURCE))[0]

        instructions = await runtime.get_prompt(prompt.capability_id, {"audience": "executives"})
        metrics = await runtime.execute(tool.capability_id)
        reference = await runtime.read_resource(resource.capability_id)

        answer = (
            f"{instructions['instructions']} "
            f"Revenue growth is {metrics['revenue_growth']}. "
            f"Reference: {reference}."
        )
        print(answer)


if __name__ == "__main__":
    asyncio.run(main())
