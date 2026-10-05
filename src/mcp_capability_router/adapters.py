"""The MCP adapter for servers that FastMCP can reach."""

from __future__ import annotations

import uuid
import warnings
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool, ToolException

from ._internal.translation import translated
from .errors import InvalidRequestError, ProtocolError, ToolExecutionError

if TYPE_CHECKING:
    from fastmcp import Client, FastMCP
    from fastmcp.client.transports import ClientTransport
    from langchain_core.tools import BaseTool
    from mcp import types

type FastMCPTarget = (
    Client[Any] | ClientTransport | FastMCP | str | Path | Mapping[str, Any]
)
"""Anything that `fastmcp.Client` accepts: a URL, a script path, an MCP
configuration dictionary, an in-process `FastMCP` server, a transport, or a
client."""


async def _as_langchain_tool(definition: types.Tool, client: Client[Any]) -> BaseTool:
    """Convert an MCP tool with `langchain.mcp`, imported on first use."""
    with warnings.catch_warnings():
        # langchain.mcp announces its beta status on import; the router documents it.
        warnings.filterwarnings("ignore", message="`langchain.mcp` is in beta")
        from langchain.mcp import as_langchain_tool

    return await as_langchain_tool(definition, client)


class FastMCPAdapter:
    """Connects the runtime to an MCP server through a FastMCP client.

    Works with every server and transport that FastMCP supports: Streamable HTTP
    URLs, Python or Node scripts over stdio, MCP configuration dictionaries,
    in-process `FastMCP` servers, and prebuilt `fastmcp.Client` instances with
    their own authentication, headers, and handlers.

    The client session is opened by `connect` and held until `close`, so every
    operation reuses one connection. Discovery returns metadata only; resources
    are not read until `read_resource` is called.

    Results:

    - `call_tool` returns a `langchain_core.messages.ToolMessage` whose `content`
      holds LangChain content blocks and whose `artifact` holds the structured
      content, converted by LangChain's `langchain.mcp` module (in beta). A tool
      that reports an error raises `ToolExecutionError`.
    - `read_resource` returns the MCP resource contents: a list of
      `mcp.types.TextResourceContents` and `mcp.types.BlobResourceContents`.
    - `get_prompt` returns the MCP `mcp.types.GetPromptResult`.

    FastMCP, MCP, and transport errors are translated into the router's
    `ServerError` subclasses, so the resilience pipeline classifies them.
    """

    def __init__(self, target: FastMCPTarget) -> None:
        """Create an adapter for `target`.

        Args:
            target: A `fastmcp.Client`, or anything a `fastmcp.Client` accepts.
        """
        from fastmcp import Client

        self._client: Client[Any] = (
            target if isinstance(target, Client) else Client(cast("Any", target))
        )
        self._definitions: dict[str, types.Tool] = {}
        self._tools: dict[str, BaseTool] = {}
        self._connected = False

    @property
    def client(self) -> Client[Any]:
        """The FastMCP client that this adapter uses."""
        return self._client

    async def connect(self) -> None:
        """Open the client session; do nothing if it is already open."""
        if self._connected:
            return
        await translated(self._client.__aenter__())
        self._connected = True

    async def close(self) -> None:
        """Close the client session; do nothing if it is not open."""
        if not self._connected:
            return
        self._connected = False
        self._definitions.clear()
        self._tools.clear()
        await self._client.__aexit__(None, None, None)

    async def list_tools(self) -> list[types.Tool]:
        """Return the tools of the server, or none if it does not offer tools."""
        tools = await self._list("tools", self._client.list_tools)
        self._definitions = {tool.name: tool for tool in tools}
        self._tools = {
            name: tool
            for name, tool in self._tools.items()
            if name in self._definitions
        }
        return tools

    async def list_resources(self) -> list[types.Resource]:
        """Return the resources of the server, without reading them."""
        return await self._list("resources", self._client.list_resources)

    async def list_prompts(self) -> list[types.Prompt]:
        """Return the prompts of the server."""
        return await self._list("prompts", self._client.list_prompts)

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> ToolMessage:
        """Call the tool `name` and return its result as a LangChain message.

        Raises:
            ToolExecutionError: If the tool reports an error.
            InvalidRequestError: If the server has no tool named `name`.
        """
        tool = await self._langchain_tool(name)
        if not isinstance(tool, StructuredTool) or tool.coroutine is None:
            msg = f"tool {name!r} was converted to {type(tool).__name__}"
            raise ProtocolError(msg)
        # Calling the coroutine directly passes every argument through; BaseTool
        # would swallow arguments named like its own, such as `config`.
        try:
            content, artifact = await translated(tool.coroutine(**arguments))
        except ToolException as error:
            raise ToolExecutionError(str(error) or f"tool {name!r} failed") from error
        return ToolMessage(
            content=content,
            artifact=artifact,
            tool_call_id=f"call_{uuid.uuid4().hex}",
            name=name,
        )

    async def read_resource(
        self, uri: str
    ) -> list[types.TextResourceContents | types.BlobResourceContents]:
        """Read the resource at `uri`."""
        return await translated(self._client.read_resource(uri))

    async def get_prompt(
        self, name: str, arguments: Mapping[str, str]
    ) -> types.GetPromptResult:
        """Render the prompt `name` with `arguments`."""
        return await translated(self._client.get_prompt(name, dict(arguments)))

    async def _list[T](
        self,
        kind: Literal["tools", "resources", "prompts"],
        listing: Callable[[], Awaitable[list[T]]],
    ) -> list[T]:
        """List one kind of capability, if the server offers it.

        Servers advertise the kinds they offer when the session starts; many offer
        only tools. Listing a kind that the server does not offer would fail the
        whole discovery, so it is skipped, and a server that answers "method not
        found" despite advertising the kind is treated the same way.
        """
        from mcp import types
        from mcp.shared.exceptions import MCPError

        capabilities = self._client.server_capabilities
        if capabilities is not None and getattr(capabilities, kind) is None:
            return []
        try:
            return await translated(listing())
        except InvalidRequestError as error:
            cause = error.__cause__
            if (
                isinstance(cause, MCPError)
                and cause.error.code == types.METHOD_NOT_FOUND
            ):
                return []
            raise

    async def _langchain_tool(self, name: str) -> BaseTool:
        tool = self._tools.get(name)
        if tool is not None:
            return tool
        if name not in self._definitions:
            await self.list_tools()
        definition = self._definitions.get(name)
        if definition is None:
            msg = f"the server has no tool named {name!r}"
            raise InvalidRequestError(msg)
        tool = await _as_langchain_tool(definition, self._client)
        self._tools[name] = tool
        return tool
