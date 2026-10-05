"""LangChain tools that call MCP tools through a runtime."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool, ToolException

from ..errors import MCPCapabilityRouterError

if TYPE_CHECKING:
    from ..models import Tool
    from ..runtime import MCPRuntime


def _describe(error: BaseException) -> str:
    detail = str(error) or "; ".join(getattr(error, "__notes__", ()))
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


class _RoutedTool(StructuredTool):
    """Passes the tool input to the coroutine as one `arguments` dictionary.

    LangChain passes tool arguments as keyword arguments, which would hand MCP
    arguments named like LangChain's own parameters, such as `config`,
    `run_manager`, or `callbacks`, to LangChain instead of the tool.
    """

    def _to_args_and_kwargs(
        self, tool_input: str | dict[str, Any], tool_call_id: str | None
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        _, arguments = super()._to_args_and_kwargs(tool_input, tool_call_id)
        return (), {"arguments": arguments}


def capability_tool(
    runtime: MCPRuntime, capability: Tool, *, name: str | None = None
) -> StructuredTool:
    """Return a LangChain tool that calls `capability` through `runtime`.

    Router errors and timeouts become error tool messages for the model.
    """

    async def call(arguments: dict[str, Any]) -> tuple[Any, Any]:
        try:
            result = await runtime.execute(capability.capability_id, arguments)
        except (MCPCapabilityRouterError, TimeoutError) as error:
            raise ToolException(_describe(error)) from error
        if isinstance(result, ToolMessage):
            return result.content, result.artifact
        return result, None

    return _RoutedTool(
        name=name or capability.name,
        description=capability.description or capability.title or capability.name,
        args_schema=dict(capability.input_schema),
        coroutine=call,
        response_format="content_and_artifact",
        handle_tool_error=True,
        metadata={
            "capability_id": capability.capability_id,
            "server_id": capability.server_id,
        },
    )
