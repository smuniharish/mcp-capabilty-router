"""Real-client integration coverage for LangChainMCPAdapter resource handling."""

from __future__ import annotations

import os

import pytest
from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router.integrations.langchain_mcp import LangChainMCPAdapter


def everything_client() -> MultiServerMCPClient:
    if os.name == "nt":
        command = "cmd"
        args = ["/c", "npx", "-y", "@modelcontextprotocol/server-everything"]
    else:
        command = "npx"
        args = ["-y", "@modelcontextprotocol/server-everything"]
    return MultiServerMCPClient(
        {
            "everything": {
                "command": command,
                "args": args,
                "transport": "stdio",
            }
        },
        handle_tool_errors=False,
    )


@pytest.mark.asyncio
async def test_real_client_discovers_and_reads_everything_resources() -> None:
    client = everything_client()
    adapter = LangChainMCPAdapter(client, "everything", discover_resources=True)

    entries = await adapter.list_resources()

    assert len(entries) >= 2
    assert all(entry["uri"].startswith("demo://resource/") for entry in entries)
    assert all(entry["name"] for entry in entries)

    architecture = next(entry for entry in entries if entry["name"] == "architecture.md")
    content = await adapter.read_resource(architecture["uri"])
    assert "# Everything Server" in content
    assert "Architecture" in content


@pytest.mark.asyncio
async def test_real_client_skips_resource_connection_when_discovery_disabled() -> None:
    adapter = LangChainMCPAdapter(
        everything_client(),
        "everything",
        discover_resources=False,
    )

    assert await adapter.list_resources() == []
