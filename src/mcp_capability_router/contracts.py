"""Contracts implemented by adapters, registries, retrievers, and interceptors.

Every contract is a structural `typing.Protocol`: any object with matching methods
satisfies it, without inheriting from anything. The runtime checks adapters,
registries, and retrievers with `isinstance` when they are supplied, so an object
that misses a method fails immediately instead of on first use.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from mcp import types

    from .models import Capability, CapabilityType


class Operation(StrEnum):
    """An operation that the runtime performs on an MCP server."""

    CONNECT = "connect"
    """Open the connection of an adapter."""

    DISCOVER = "discover"
    """List the tools, resources, and prompts of a server."""

    CALL_TOOL = "call_tool"
    """Call a tool."""

    READ_RESOURCE = "read_resource"
    """Read a resource."""

    GET_PROMPT = "get_prompt"
    """Render a prompt."""


@dataclass(frozen=True, slots=True, kw_only=True)
class OperationContext:
    """Describes the operation that an interceptor wraps.

    Attributes:
        server_id: ID of the server that the operation targets.
        operation: The operation.
        capability: The capability being used, for tool calls, resource reads,
            and prompt renders.
        arguments: The arguments of a tool call or prompt render.
    """

    server_id: str
    operation: Operation
    capability: Capability | None = None
    arguments: Mapping[str, Any] | None = None


@runtime_checkable
class MCPAdapter(Protocol):
    """Connects the runtime to one MCP server.

    Listings use the MCP SDK types. `FastMCPAdapter` implements this contract for
    any server that FastMCP can reach; implement it yourself to route capabilities
    from another source.
    """

    async def connect(self) -> None:
        """Open the connection to the server."""

    async def close(self) -> None:
        """Close the connection and release its resources."""

    async def list_tools(self) -> Sequence[types.Tool]:
        """Return the tools that the server offers."""

    async def list_resources(self) -> Sequence[types.Resource]:
        """Return the resources that the server offers."""

    async def list_prompts(self) -> Sequence[types.Prompt]:
        """Return the prompts that the server offers."""

    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call the tool `name` with `arguments` and return its result."""

    async def read_resource(self, uri: str) -> Any:
        """Read the resource at `uri` and return its contents."""

    async def get_prompt(self, name: str, arguments: Mapping[str, str]) -> Any:
        """Render the prompt `name` with `arguments` and return the result."""


@runtime_checkable
class CapabilityRegistry(Protocol):
    """Stores the capability metadata of every registered server.

    `InMemoryRegistry` is the default. Implement this contract to keep metadata in
    a database shared by several processes.
    """

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        """Insert or replace `capabilities`, keyed by `capability_id`."""

    async def remove(self, capability_id: str) -> None:
        """Remove one capability; do nothing if it is not stored."""

    async def remove_server(self, server_id: str) -> None:
        """Remove every capability of the server `server_id`."""

    async def get(self, capability_id: str) -> Capability | None:
        """Return the capability `capability_id`, or `None` if it is not stored."""

    async def list(
        self,
        *,
        server_id: str | None = None,
        type: CapabilityType | None = None,
    ) -> Sequence[Capability]:
        """Return the stored capabilities, optionally filtered by server and type."""

    async def close(self) -> None:
        """Release the resources of the registry."""


@runtime_checkable
class CapabilityRetriever(Protocol):
    """Ranks candidate capabilities against a query.

    `KeywordRetriever` is the default; `EmbeddingRetriever` ranks semantically.
    """

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        """Return at most `limit` of `candidates`, best match first."""


@runtime_checkable
class Interceptor(Protocol):
    """Wraps every operation that the runtime performs on a server.

    An interceptor receives the operation context and a `call_next` function, and
    must return the result of `await call_next()` or raise. Interceptors run in
    order, inside the concurrency limit and outside the circuit breaker, so they
    observe each operation once, however many attempts it takes.

    Example:
        ```python
        async def audit(context: OperationContext, call_next):
            print(f"{context.operation} on {context.server_id}")
            return await call_next()
        ```
    """

    async def __call__(
        self, context: OperationContext, call_next: Callable[[], Awaitable[Any]], /
    ) -> Any:
        """Run the operation by awaiting `call_next()`, and return its result."""
