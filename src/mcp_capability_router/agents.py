"""LangChain integration: routed tools and agent middleware."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool, StructuredTool

from ._internal.naming import (
    qualified_tool_name,
    split_qualified_tool_name,
    validate_limit,
    validate_server_id,
)
from ._internal.tools import capability_tool
from .models import CapabilityType, Tool, make_capability_id

if TYPE_CHECKING:
    from langgraph.types import Command

    from .runtime import MCPRuntime


def _latest_user_text(messages: Sequence[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            if isinstance(content, str):
                return content
            parts = (
                block if isinstance(block, str) else str(block.get("text", ""))
                for block in content
                if isinstance(block, str)
                or (isinstance(block, Mapping) and block.get("type") == "text")
            )
            return " ".join(part for part in parts if part)
    return ""


class CapabilityRoutingMiddleware(AgentMiddleware):
    """Gives a LangChain agent only the MCP tools that are relevant to each turn.

    Before every model call, the middleware queries the runtime with the latest
    user message and adds the best matching tools to the call, next to the tools
    the agent was created with. Calls to those tools run through the runtime, so
    the resilience pipeline, metrics, and health tracking apply. The model never
    sees the full catalog, however many servers and tools are registered.

    Failures of routed tools reach the model as error tool messages, so the agent
    can recover instead of aborting the run.

    Tool names are the MCP tool names when the middleware is limited to one
    server; otherwise they are prefixed with the server ID, as in
    `filesystem_read_text_file`, so tools of different servers never collide.

    The middleware is asynchronous; invoke the agent with `ainvoke` or `astream`.

    Example:
        ```python
        from langchain.agents import create_agent

        agent = create_agent(
            "openai:gpt-5.4-mini",
            tools=[],
            middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
        )
        result = await agent.ainvoke({"messages": [{"role": "user", "content": "..."}]})
        ```
    """

    def __init__(
        self, runtime: MCPRuntime, *, limit: int = 5, server_id: str | None = None
    ) -> None:
        """Create the middleware.

        Args:
            runtime: The runtime that retrieves and calls the tools.
            limit: The maximum number of routed tools per model call.
            server_id: Route only the tools of this server.

        Raises:
            ConfigurationError: If `limit` or `server_id` is invalid.
        """
        super().__init__()
        self._runtime = runtime
        self._limit = validate_limit(limit)
        self._server_id = (
            validate_server_id(server_id) if server_id is not None else None
        )

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Add the tools that match the latest user message to the model call."""
        query = _latest_user_text(request.messages)
        if query:
            capabilities = await self._runtime.query(
                query,
                type=CapabilityType.TOOL,
                server_id=self._server_id,
                limit=self._limit,
            )
            present = {
                tool.name for tool in request.tools if isinstance(tool, BaseTool)
            }
            routed = [
                self._tool(capability)
                for capability in capabilities
                if isinstance(capability, Tool)
            ]
            routed = [tool for tool in routed if tool.name not in present]
            if routed:
                request = request.override(tools=[*request.tools, *routed])
        return await handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Run calls of routed tools through the runtime."""
        if request.tool is not None:
            return await handler(request)
        name = request.tool_call["name"]
        matches = await self._resolve(name)
        if len(matches) > 1:
            servers = ", ".join(sorted(match.server_id for match in matches))
            return ToolMessage(
                content=f"Tool name {name!r} is ambiguous between servers: {servers}",
                tool_call_id=request.tool_call["id"] or "",
                name=name,
                status="error",
            )
        if matches:
            request = request.override(tool=self._tool(matches[0]))
        return await handler(request)

    def _tool(self, capability: Tool) -> StructuredTool:
        name = (
            capability.name
            if self._server_id is not None
            else qualified_tool_name(capability.server_id, capability.name)
        )
        return capability_tool(self._runtime, capability, name=name)

    async def _resolve(self, name: str) -> list[Tool]:
        candidates = (
            [(self._server_id, name)]
            if self._server_id is not None
            else split_qualified_tool_name(name, self._runtime.servers)
        )
        matches: list[Tool] = []
        for server_id, tool_name in candidates:
            capability = await self._runtime.registry.get(
                make_capability_id(server_id, CapabilityType.TOOL, tool_name)
            )
            if isinstance(capability, Tool):
                matches.append(capability)
        return matches
