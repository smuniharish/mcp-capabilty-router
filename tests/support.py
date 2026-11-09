"""Test doubles shared by the test suites."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from mcp import types

from mcp_capability_router import Capability, MCPAdapter, Prompt, Resource, Tool

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


def mcp_tool(name: str, description: str = "", **fields: Any) -> types.Tool:
    """Build an MCP tool definition."""
    fields.setdefault("input_schema", {"type": "object", "properties": {}})
    return types.Tool(name=name, description=description, **fields)


def mcp_resource(uri: str, name: str, description: str = "", **fields: Any) -> types.Resource:
    """Build an MCP resource definition."""
    return types.Resource(uri=uri, name=name, description=description, **fields)


def mcp_prompt(name: str, description: str = "", **fields: Any) -> types.Prompt:
    """Build an MCP prompt definition."""
    return types.Prompt(name=name, description=description, **fields)


def tool(server_id: str, name: str, description: str = "", **fields: Any) -> Tool:
    """Build a tool capability with the router's ID convention."""
    return Tool(
        capability_id=f"{server_id}:tool:{name}",
        server_id=server_id,
        name=name,
        description=description,
        **fields,
    )


def resource(server_id: str, uri: str, name: str, **fields: Any) -> Resource:
    """Build a resource capability with the router's ID convention."""
    return Resource(
        capability_id=f"{server_id}:resource:{uri}",
        server_id=server_id,
        name=name,
        uri=uri,
        **fields,
    )


def prompt(server_id: str, name: str, **fields: Any) -> Prompt:
    """Build a prompt capability with the router's ID convention."""
    return Prompt(
        capability_id=f"{server_id}:prompt:{name}",
        server_id=server_id,
        name=name,
        **fields,
    )


class FakeAdapter(MCPAdapter):
    """An in-memory MCP adapter that records calls and can fail on demand.

    Set `failures[method]` to a list of exceptions; each call of `method` raises
    the next one until the list is empty.
    """

    def __init__(
        self,
        tools: Sequence[types.Tool] = (),
        resources: Sequence[types.Resource] = (),
        prompts: Sequence[types.Prompt] = (),
    ) -> None:
        self.tools = list(tools)
        self.resources = list(resources)
        self.prompts = list(prompts)
        self.failures: dict[str, list[BaseException]] = {}
        self.calls: list[tuple[str, Any]] = []
        self.connects = 0
        self.closes = 0
        self.connected = False
        self.delay = 0.0

    async def _step(self, method: str, detail: Any = None) -> None:
        self.calls.append((method, detail))
        if self.delay:
            await asyncio.sleep(self.delay)
        pending = self.failures.get(method)
        if pending:
            raise pending.pop(0)

    async def connect(self) -> None:
        await self._step("connect")
        self.connects += 1
        self.connected = True

    async def close(self) -> None:
        self.closes += 1
        self.connected = False
        await self._step("close")

    async def list_tools(self) -> list[types.Tool]:
        await self._step("list_tools")
        return list(self.tools)

    async def list_resources(self) -> list[types.Resource]:
        await self._step("list_resources")
        return list(self.resources)

    async def list_prompts(self) -> list[types.Prompt]:
        await self._step("list_prompts")
        return list(self.prompts)

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        await self._step("call_tool", (name, dict(arguments)))
        return {"tool": name, "arguments": dict(arguments)}

    async def read_resource(self, uri: str) -> Any:
        await self._step("read_resource", uri)
        return f"contents of {uri}"

    async def get_prompt(self, name: str, arguments: Mapping[str, str]) -> Any:
        await self._step("get_prompt", (name, dict(arguments)))
        return f"prompt {name} with {dict(arguments)}"


def demo_server() -> FastMCP:
    """Return an in-process MCP server with tools, resources, and prompts."""
    server = FastMCP("demo")

    @server.tool(tags={"math"}, annotations={"readOnlyHint": True})
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    @server.tool
    def fail(reason: str) -> str:
        """Always fail with the given reason."""
        raise ValueError(reason)

    @server.resource(
        "resource://notes/readme",
        name="readme",
        description="Project readme",
        mime_type="text/markdown",
    )
    def readme() -> str:
        return "# Hello"

    @server.resource("resource://images/pixel", name="pixel", mime_type="image/png")
    def pixel() -> bytes:
        return b"\x89PNG\r\n"

    @server.prompt(description="Summarize a topic")
    def summarize(topic: str, tone: str = "neutral") -> str:
        return f"Summarize {topic} in a {tone} tone."

    return server


def capability_ids(capabilities: Sequence[Capability]) -> list[str]:
    """Return the IDs of `capabilities`, in order."""
    return [capability.capability_id for capability in capabilities]
