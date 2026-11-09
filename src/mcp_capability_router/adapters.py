"""The MCP adapter for servers that FastMCP can reach."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from ._internal.translation import translated
from .contracts import MCPAdapter
from .errors import ConfigurationError, InvalidRequestError, ToolExecutionError

if TYPE_CHECKING:
    from fastmcp import Client, FastMCP
    from fastmcp.client.client import CallToolResult
    from fastmcp.client.transports import ClientTransport
    from mcp import types

type FastMCPTarget = Client[Any] | ClientTransport | FastMCP | str | Path | Mapping[str, Any]
"""Anything that `fastmcp.Client` accepts: a URL, a script path, an MCP
configuration dictionary, an in-process `FastMCP` server, a transport, or a
client."""


class FastMCPAdapter(MCPAdapter):
    """Connects the runtime to an MCP server through a FastMCP client.

    Works with every server and transport that FastMCP supports: Streamable HTTP
    URLs, Python or Node scripts over stdio, MCP configuration dictionaries,
    in-process `FastMCP` servers, and prebuilt `fastmcp.Client` instances with
    their own authentication, headers, and handlers.

    The client session is opened by `connect` and held until `close`, so every
    operation reuses one connection. Discovery returns metadata only; resources
    are not read until `read_resource` is called.

    Results:

    - `call_tool` returns FastMCP's `CallToolResult`: the MCP content blocks,
      the structured content, the result metadata, and `data`, the structured
      content parsed against the tool's output schema. A tool that reports an
      error raises `ToolExecutionError`.
    - `read_resource` returns the MCP resource contents: a list of
      `mcp.types.TextResourceContents` and `mcp.types.BlobResourceContents`.
    - `get_prompt` returns the MCP `mcp.types.GetPromptResult`.

    FastMCP, MCP, and transport errors are translated into the router's
    `ServerError` subclasses, so the resilience pipeline classifies them.
    """

    def __init__(self, target: FastMCPTarget, **client_options: Any) -> None:
        """Create an adapter for `target`.

        Args:
            target: A `fastmcp.Client`, or anything a `fastmcp.Client` accepts.
            **client_options: Keyword arguments of the `fastmcp.Client` created
                for `target`, such as `auth`, `timeout`, `init_timeout`,
                `client_info`, `roots`, or the sampling, elicitation, logging,
                progress, and message handlers.

        Raises:
            ConfigurationError: If `client_options` are given with a prebuilt
                `fastmcp.Client`, which is configured already.
        """
        from fastmcp import Client

        if isinstance(target, Client):
            if client_options:
                msg = (
                    "client options cannot be applied to a prebuilt fastmcp.Client; "
                    "configure the client instead"
                )
                raise ConfigurationError(msg)
            self._client: Client[Any] = target
        else:
            self._client = Client(cast("Any", target), **client_options)
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
        await self._client.__aexit__(None, None, None)

    async def list_tools(self) -> list[types.Tool]:
        """Return the tools of the server, or none if it does not offer tools."""
        return await self._list("tools", self._client.list_tools)

    async def list_resources(self) -> list[types.Resource]:
        """Return the resources of the server, without reading them."""
        return await self._list("resources", self._client.list_resources)

    async def list_prompts(self) -> list[types.Prompt]:
        """Return the prompts of the server."""
        return await self._list("prompts", self._client.list_prompts)

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> CallToolResult:
        """Call the tool `name` and return its result.

        Raises:
            ToolExecutionError: If the tool reports an error, including when
                the server has no tool named `name`.
            InvalidRequestError: If the server rejects the request.
        """
        result = await translated(
            self._client.call_tool(name, dict(arguments), raise_on_error=False)
        )
        if result.is_error:
            raise ToolExecutionError(_error_text(result) or f"tool {name!r} failed")
        return result

    async def read_resource(
        self, uri: str
    ) -> list[types.TextResourceContents | types.BlobResourceContents]:
        """Read the resource at `uri`."""
        return await translated(self._client.read_resource(uri))

    async def get_prompt(self, name: str, arguments: Mapping[str, str]) -> types.GetPromptResult:
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
            if isinstance(cause, MCPError) and cause.error.code == types.METHOD_NOT_FOUND:
                return []
            raise


def _error_text(result: CallToolResult) -> str:
    """Join the text blocks of a failed tool result into one message."""
    from mcp import types

    return "\n".join(
        block.text for block in result.content if isinstance(block, types.TextContent)
    ).strip()
