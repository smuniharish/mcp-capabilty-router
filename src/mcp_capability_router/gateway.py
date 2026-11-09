"""The MCP gateway: the router served as one MCP server."""

from __future__ import annotations

import base64
import importlib.util
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.exceptions import PromptError, ResourceError, ToolError
from fastmcp.prompts.base import Message, PromptResult
from fastmcp.prompts.base import Prompt as MCPPrompt
from fastmcp.prompts.base import PromptArgument as MCPPromptArgument
from fastmcp.resources.base import Resource as MCPResource
from fastmcp.resources.base import ResourceContent, ResourceResult
from fastmcp.server.context import Context  # noqa: TC002 - FastMCP reads the annotation
from fastmcp.server.providers import Provider
from fastmcp.server.transforms.search.base import BaseSearchTransform
from fastmcp.tools.base import Tool as MCPTool
from fastmcp.tools.base import ToolResult
from mcp import types
from pydantic import PrivateAttr

from ._internal.naming import qualified_tool_name, validate_positive
from .errors import ConfigurationError, MCPCapabilityRouterError
from .models import Capability, CapabilityType, Prompt, Resource, Tool

if TYPE_CHECKING:
    from fastmcp.utilities.versions import VersionSpec

    from .runtime import MCPRuntime

type GatewayMode = Literal["search", "catalog", "code"]
"""What an MCP client sees of the gateway's tools.

- `"search"`: a `search_tools` tool that ranks the tools with the runtime's
  retriever, and a `call_tool` tool that calls a found tool.
- `"catalog"`: every tool of every registered server.
- `"code"`: experimental code mode: `search` and `get_schema` tools to find tools,
  and an `execute` tool that runs Python which calls them in a sandbox; needs the
  `codemode` extra.
"""

_META_KEY = "mcp_capability_router"


def _describe(error: BaseException) -> str:
    detail = str(error) or "; ".join(getattr(error, "__notes__", ()))
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def _meta(capability: Capability) -> dict[str, Any]:
    return {
        _META_KEY: {"capability_id": capability.capability_id, "server_id": capability.server_id}
    }


def _capability_id(meta: dict[str, Any] | None) -> str | None:
    value = (meta or {}).get(_META_KEY)
    return value.get("capability_id") if isinstance(value, dict) else None


class _GatewayTool(MCPTool):
    """A tool of a registered server, called through the runtime."""

    _runtime: MCPRuntime = PrivateAttr()

    @classmethod
    def build(cls, runtime: MCPRuntime, tool: Tool) -> _GatewayTool:
        annotations = tool.metadata.get("annotations")
        component = cls(
            name=qualified_tool_name(tool.server_id, tool.name),
            title=tool.title,
            description=tool.description or None,
            parameters=dict(tool.input_schema),
            output_schema=dict(tool.output_schema) if tool.output_schema is not None else None,
            annotations=(
                types.ToolAnnotations.model_validate(dict(annotations))
                if isinstance(annotations, dict)
                else None
            ),
            tags=set(tool.tags),
            meta=_meta(tool),
        )
        component._runtime = runtime
        return component

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        """Call the tool through the runtime."""
        capability_id = _capability_id(self.meta)
        try:
            result = await self._runtime.execute(str(capability_id), arguments)
        except (MCPCapabilityRouterError, TimeoutError) as error:
            raise ToolError(_describe(error)) from error
        if isinstance(result, CallToolResult):
            return ToolResult(
                content=result.content,
                structured_content=result.structured_content,
                meta=result.meta,
            )
        return ToolResult(content=result)


class _GatewayResource(MCPResource):
    """A resource of a registered server, read through the runtime."""

    _runtime: MCPRuntime = PrivateAttr()

    @classmethod
    def build(cls, runtime: MCPRuntime, resource: Resource) -> _GatewayResource:
        component = cls(
            uri=resource.uri,
            name=resource.name,
            title=resource.title,
            description=resource.description or None,
            mime_type=resource.mime_type or "text/plain",
            tags=set(resource.tags),
            meta=_meta(resource),
        )
        component._runtime = runtime
        return component

    async def read(self) -> ResourceResult:
        """Read the resource through the runtime."""
        capability_id = _capability_id(self.meta)
        try:
            result = await self._runtime.read_resource(str(capability_id))
        except (MCPCapabilityRouterError, TimeoutError) as error:
            raise ResourceError(_describe(error)) from error
        if not isinstance(result, Sequence) or isinstance(result, str | bytes):
            return ResourceResult(contents=[ResourceContent(result, mime_type=self.mime_type)])
        contents = [
            ResourceContent(
                base64.b64decode(item.blob)
                if isinstance(item, types.BlobResourceContents)
                else getattr(item, "text", item),
                mime_type=getattr(item, "mime_type", None) or self.mime_type,
            )
            for item in result
        ]
        return ResourceResult(contents=contents)


class _GatewayPrompt(MCPPrompt):
    """A prompt of a registered server, rendered through the runtime."""

    _runtime: MCPRuntime = PrivateAttr()

    @classmethod
    def build(cls, runtime: MCPRuntime, prompt: Prompt) -> _GatewayPrompt:
        component = cls(
            name=qualified_tool_name(prompt.server_id, prompt.name),
            title=prompt.title,
            description=prompt.description or None,
            arguments=[
                MCPPromptArgument(
                    name=argument.name,
                    description=argument.description or None,
                    required=argument.required,
                )
                for argument in prompt.arguments
            ],
            tags=set(prompt.tags),
            meta=_meta(prompt),
        )
        component._runtime = runtime
        return component

    async def render(self, arguments: dict[str, Any] | None = None) -> PromptResult:
        """Render the prompt through the runtime."""
        capability_id = _capability_id(self.meta)
        values = {key: str(value) for key, value in (arguments or {}).items()}
        try:
            result = await self._runtime.get_prompt(str(capability_id), values)
        except (MCPCapabilityRouterError, TimeoutError) as error:
            raise PromptError(_describe(error)) from error
        if isinstance(result, types.GetPromptResult):
            return PromptResult(
                messages=[
                    Message(message.content, role=message.role) for message in result.messages
                ],
                description=result.description,
                meta=result.meta,
            )
        return PromptResult(messages=str(result))


class RouterProvider(Provider):
    """Serves the capabilities of a runtime as FastMCP components.

    Tools and prompts are named `{server_id}_{name}`, as `MCPRuntime.route_tools`
    names tools of several servers, so names never collide. Resources keep their
    URIs; when several servers offer the same URI, the server registered first
    serves it. Every call runs through the runtime, so the resilience pipeline,
    interceptors, metrics, and health tracking apply. The listing follows the
    registry, so refreshed servers show up without restarting the gateway.

    `MCPRuntime.as_mcp_server` builds a server with this provider; add it to a
    `FastMCP` server of your own to mix the router with other components.
    """

    def __init__(self, runtime: MCPRuntime) -> None:
        """Serve the capabilities of `runtime`."""
        super().__init__()
        self._runtime = runtime

    @property
    def runtime(self) -> MCPRuntime:
        """The runtime whose capabilities are served."""
        return self._runtime

    async def _capabilities(self, kind: CapabilityType) -> Sequence[Capability]:
        capabilities = await self._runtime.registry.list(type=kind)
        order = {server_id: index for index, server_id in enumerate(self._runtime.servers)}
        return sorted(
            capabilities,
            key=lambda c: (order.get(c.server_id, len(order)), c.capability_id),
        )

    async def _list_tools(self) -> Sequence[MCPTool]:
        return [
            _GatewayTool.build(self._runtime, tool)
            for tool in await self._capabilities(CapabilityType.TOOL)
            if isinstance(tool, Tool)
        ]

    async def _get_tool(
        self,
        name: str,
        version: VersionSpec | None = None,  # noqa: ARG002 - one version per tool
    ) -> MCPTool | None:
        try:
            tool = await self._runtime.resolve_tool(name)
        except MCPCapabilityRouterError as error:
            raise ToolError(_describe(error)) from error
        return _GatewayTool.build(self._runtime, tool.capability) if tool is not None else None

    async def _list_resources(self) -> Sequence[MCPResource]:
        seen: set[str] = set()
        components: list[MCPResource] = []
        for resource in await self._capabilities(CapabilityType.RESOURCE):
            if isinstance(resource, Resource) and resource.uri not in seen:
                seen.add(resource.uri)
                components.append(_GatewayResource.build(self._runtime, resource))
        return components

    async def _get_resource(
        self,
        uri: str,
        version: VersionSpec | None = None,  # noqa: ARG002 - one version per resource
    ) -> MCPResource | None:
        for component in await self._list_resources():
            if str(component.uri) == uri:
                return component
        return None

    async def _list_prompts(self) -> Sequence[MCPPrompt]:
        return [
            _GatewayPrompt.build(self._runtime, prompt)
            for prompt in await self._capabilities(CapabilityType.PROMPT)
            if isinstance(prompt, Prompt)
        ]

    async def _get_prompt(
        self,
        name: str,
        version: VersionSpec | None = None,  # noqa: ARG002 - one version per prompt
    ) -> MCPPrompt | None:
        for component in await self._list_prompts():
            if component.name == name:
                return component
        return None


class _Ranker:
    """Ranks gateway tools with the runtime's retriever."""

    def __init__(self, runtime: MCPRuntime, limit: int) -> None:
        self._runtime = runtime
        self._limit = limit

    async def __call__(self, tools: Sequence[MCPTool], query: str) -> Sequence[MCPTool]:
        by_id = {
            capability_id: tool
            for tool in tools
            if (capability_id := _capability_id(tool.meta)) is not None
        }
        if not by_id:
            return []
        matches = await self._runtime.query(
            query,
            type=CapabilityType.TOOL,
            limit=min(self._limit, len(by_id)),
            where=lambda capability: capability.capability_id in by_id,
        )
        return [by_id[match.capability_id] for match in matches]


class RouterSearchTransform(BaseSearchTransform):
    """Replaces the tool listing with `search_tools` and `call_tool`.

    `search_tools` ranks the tools with the runtime's retriever, so a client
    finds tools by what they do, as `MCPRuntime.route_tools` does. `call_tool`
    calls a found tool; tools also stay callable by name.
    """

    def __init__(self, runtime: MCPRuntime, *, max_results: int = 5, **options: Any) -> None:
        """Rank with `runtime`, returning at most `max_results` tools per search.

        Args:
            runtime: The runtime whose retriever ranks the tools.
            max_results: The maximum number of tools per search.
            **options: Options of FastMCP's `BaseSearchTransform`, such as
                `always_visible` or `search_tool_name`.
        """
        super().__init__(max_results=max_results, **options)
        self._rank = _Ranker(runtime, max_results)

    def _make_search_tool(self) -> MCPTool:
        transform = self

        async def search_tools(
            query: Annotated[str, "What the tool should do, in natural language"],
            ctx: Context = None,  # type: ignore[assignment]
        ) -> str | list[dict[str, Any]]:
            """Find the tools that best match a description of the task.

            Returns the matching tool definitions, best first, in the format of
            list_tools. Call them with call_tool.
            """
            tools = await transform._get_visible_tools(ctx)
            return await transform._render_results(await transform._search(tools, query))

        return MCPTool.from_function(fn=search_tools, name=self._search_tool_name)

    async def _search(self, tools: Sequence[MCPTool], query: str) -> Sequence[MCPTool]:
        return await self._rank(tools, query)


def build_server(
    runtime: MCPRuntime,
    *,
    name: str,
    mode: GatewayMode,
    max_results: int,
    **server_options: Any,
) -> FastMCP:
    """Build the gateway server; see `MCPRuntime.as_mcp_server`."""
    validate_positive("max_results", max_results)
    transforms = list(server_options.pop("transforms", None) or ())
    if mode == "search":
        transforms.insert(0, RouterSearchTransform(runtime, max_results=max_results))
    elif mode == "code":
        if importlib.util.find_spec("pydantic_monty") is None:
            msg = (
                'code mode needs the codemode extra: pip install "mcp-capability-router[codemode]"'
            )
            raise ConfigurationError(msg)
        from fastmcp.experimental.transforms.code_mode import CodeMode, GetSchemas, Search

        transforms.insert(
            0,
            CodeMode(
                discovery_tools=[
                    Search(search_fn=_Ranker(runtime, max_results), default_limit=max_results),
                    GetSchemas(),
                ]
            ),
        )
    elif mode != "catalog":
        msg = f"mode must be 'search', 'catalog', or 'code', got {mode!r}"
        raise ConfigurationError(msg)
    providers = [RouterProvider(runtime), *(server_options.pop("providers", None) or ())]
    return FastMCP(name, providers=providers, transforms=transforms, **server_options)
