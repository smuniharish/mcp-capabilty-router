from __future__ import annotations

import pytest

from mcp_capability_router import CapabilityType, MCPRuntime


class WorkspaceAdapter:
    """Exposes a Tool, a Resource, and a Prompt from a single server, in-process.

    This models a realistic end-to-end workflow: a prompt supplies instructions, a
    tool fetches live data, and a resource supplies reference material, all routed
    through the same runtime without any network dependency.
    """

    def __init__(self):
        self.connected = False
        self._documents = {"reference.txt": "quarterly revenue rose 12%"}

    async def connect(self):
        self.connected = True

    async def close(self):
        self.connected = False

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
        assert name == "fetch_metrics"
        return {"revenue_growth": "12%"}

    async def read_resource(self, uri):
        assert uri == "file:///reference.txt"
        return self._documents["reference.txt"]

    async def get_prompt(self, name, arguments=None):
        assert name == "summarize"
        audience = (arguments or {}).get("audience", "general")
        return {"instructions": f"Summarize the metrics for a {audience} audience."}


@pytest.mark.asyncio
async def test_combined_tool_resource_prompt_workflow():
    adapter = WorkspaceAdapter()
    async with MCPRuntime() as runtime:
        await runtime.register_server("workspace", lambda: adapter)
        await runtime.refresh_server("workspace")

        prompts = await runtime.retrieve("summarize", type=CapabilityType.PROMPT)
        tools = await runtime.retrieve("metrics", type=CapabilityType.TOOL)
        resources = await runtime.retrieve("reference", type=CapabilityType.RESOURCE)
        assert len(prompts) == len(tools) == len(resources) == 1

        # Step 1: obtain instructions from the prompt.
        prompt_result = await runtime.get_prompt(
            prompts[0].capability_id, {"audience": "executives"}
        )
        assert "executives" in prompt_result["instructions"]

        # Step 2: fetch live data via the tool.
        tool_result = await runtime.execute(tools[0].capability_id)
        assert tool_result["revenue_growth"] == "12%"

        # Step 3: read reference material via the resource.
        reference_text = await runtime.read_resource(resources[0].capability_id)
        assert "revenue" in reference_text

        # Step 4: combine all three into a single downstream answer.
        answer = (
            f"{prompt_result['instructions']} "
            f"Revenue growth is {tool_result['revenue_growth']}. "
            f"Reference: {reference_text}."
        )
        assert "executives" in answer
        assert "12%" in answer
        assert "revenue" in answer


@pytest.mark.asyncio
async def test_combined_workflow_isolates_capability_types():
    """Calling execute/read_resource/get_prompt on the wrong capability type must fail clearly."""
    adapter = WorkspaceAdapter()
    async with MCPRuntime() as runtime:
        await runtime.register_server("workspace", lambda: adapter)
        await runtime.refresh_server("workspace")

        tool = (await runtime.retrieve("metrics", type=CapabilityType.TOOL))[0]
        resource = (await runtime.retrieve("reference", type=CapabilityType.RESOURCE))[0]
        prompt = (await runtime.retrieve("summarize", type=CapabilityType.PROMPT))[0]

        from mcp_capability_router.errors import ServerError

        with pytest.raises(ServerError):
            await runtime.execute(resource.capability_id)
        with pytest.raises(ServerError):
            await runtime.read_resource(prompt.capability_id)
        with pytest.raises(ServerError):
            await runtime.get_prompt(tool.capability_id)
