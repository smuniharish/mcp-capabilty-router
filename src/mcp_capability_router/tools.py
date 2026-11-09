"""Routed tools: framework-neutral handles for calling MCP tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

    from .models import Tool
    from .runtime import MCPRuntime


@dataclass(frozen=True, slots=True)
class RoutedTool:
    """A tool that an agent framework can show to a model and call.

    It holds what a framework needs to describe the tool to a model, the name, the
    description, and the JSON schemas, and calls the tool through the runtime, so
    the resilience pipeline, interceptors, metrics, and health tracking apply.
    `MCPRuntime.route_tools` and `MCPRuntime.resolve_tool` create routed tools;
    framework integrations, such as `mcp_capability_router.integrations.langchain`,
    convert them into the framework's own tool type.

    Example:
        ```python
        for tool in await runtime.route_tools("read a file", limit=5):
            print(tool.name, tool.input_schema)
        result = await tool({"path": "README.md"})
        ```
    """

    name: str
    """The name shown to the model, prefixed with the server ID when tools of
    several servers mix."""
    capability: Tool
    """The routed tool's metadata."""
    runtime: MCPRuntime = field(repr=False, compare=False)
    """The runtime that calls the tool."""

    @property
    def capability_id(self) -> str:
        """The ID of the routed tool."""
        return self.capability.capability_id

    @property
    def server_id(self) -> str:
        """The ID of the server that offers the tool."""
        return self.capability.server_id

    @property
    def description(self) -> str:
        """The tool description; the title or the name when the server gives none."""
        return self.capability.description or self.capability.title or self.capability.name

    @property
    def input_schema(self) -> Mapping[str, Any]:
        """The JSON schema of the tool arguments."""
        return self.capability.input_schema

    @property
    def output_schema(self) -> Mapping[str, Any] | None:
        """The JSON schema of the structured result, if the server declares one."""
        return self.capability.output_schema

    async def __call__(self, arguments: Mapping[str, Any] | None = None) -> Any:
        """Call the tool through the runtime and return its result.

        Returns:
            Whatever the adapter returns; FastMCP's `CallToolResult` for
            `FastMCPAdapter`.

        Raises:
            CapabilityNotFoundError: If the tool is no longer known.
            CircuitOpenError: If the circuit of the server is open.
            ServerError: If the server operation fails, including
                `ToolExecutionError` when the tool reports an error.
            RuntimeClosedError: If the runtime is closed.
        """
        return await self.runtime.execute(self.capability_id, arguments)
