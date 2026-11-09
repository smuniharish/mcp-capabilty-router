"""Abstract base classes for adapters, registries, retrievers, and interceptors.

Every extension point is an `abc.ABC`: subclass it and implement its abstract methods.
The runtime checks the objects it receives with `isinstance` and raises
`ConfigurationError` for one that does not subclass the expected base class, so a
misconfigured runtime fails when it is created instead of on first use.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from ._internal.concurrency import gather_or_cancel

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


class MCPAdapter(ABC):
    """Connects the runtime to one MCP server.

    Listings use the MCP SDK types. `FastMCPAdapter` implements this class for any
    server that FastMCP can reach; subclass it to route capabilities from another
    source.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Open the connection to the server."""

    @abstractmethod
    async def close(self) -> None:
        """Close the connection and release its resources."""

    @abstractmethod
    async def list_tools(self) -> Sequence[types.Tool]:
        """Return the tools that the server offers."""

    @abstractmethod
    async def list_resources(self) -> Sequence[types.Resource]:
        """Return the resources that the server offers."""

    @abstractmethod
    async def list_prompts(self) -> Sequence[types.Prompt]:
        """Return the prompts that the server offers."""

    @abstractmethod
    async def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        """Call the tool `name` with `arguments` and return its result."""

    @abstractmethod
    async def read_resource(self, uri: str) -> Any:
        """Read the resource at `uri` and return its contents."""

    @abstractmethod
    async def get_prompt(self, name: str, arguments: Mapping[str, str]) -> Any:
        """Render the prompt `name` with `arguments` and return the result."""


type AdapterFactory = Callable[[], MCPAdapter | Awaitable[MCPAdapter]]
"""Creates the adapter of a server; a plain function or an async function."""


class CapabilityRegistry(ABC):
    """Stores the capability metadata of every registered server.

    `InMemoryRegistry` is the default. Subclass it to keep metadata in a database
    shared by several processes; `mcp_capability_router.testing` provides a contract
    test suite for implementations.
    """

    @abstractmethod
    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        """Insert or replace `capabilities`, keyed by `capability_id`."""

    @abstractmethod
    async def remove(self, capability_id: str) -> None:
        """Remove one capability; do nothing if it is not stored."""

    @abstractmethod
    async def remove_server(self, server_id: str) -> None:
        """Remove every capability of the server `server_id`."""

    @abstractmethod
    async def get(self, capability_id: str) -> Capability | None:
        """Return the capability `capability_id`, or `None` if it is not stored."""

    async def get_many(self, capability_ids: Iterable[str]) -> dict[str, Capability]:
        """Return the stored capabilities among `capability_ids`, by ID.

        IDs that are not stored are absent from the result. The default
        implementation calls `get` concurrently for each distinct ID; override it
        to fetch every capability in one round trip.
        """
        ids = list(dict.fromkeys(capability_ids))
        found = await gather_or_cancel(*(self.get(capability_id) for capability_id in ids))
        return {
            capability_id: capability
            for capability_id, capability in zip(ids, found, strict=True)
            if capability is not None
        }

    @abstractmethod
    async def list(
        self,
        *,
        server_id: str | None = None,
        type: CapabilityType | None = None,
    ) -> Sequence[Capability]:
        """Return the stored capabilities, optionally filtered by server and type."""

    async def close(self) -> None:  # noqa: B027
        """Release the resources of the registry; does nothing by default."""


class CapabilityRetriever(ABC):
    """Ranks candidate capabilities against a query.

    `KeywordRetriever` is the default; `EmbeddingRetriever` ranks semantically, and
    `HybridRetriever` fuses the rankings of several retrievers.
    """

    @abstractmethod
    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        """Return at most `limit` of `candidates`, best match first."""


type CallNext = Callable[[], Awaitable[Any]]
"""Runs the rest of the pipeline and returns the result of the operation."""


class Interceptor(ABC):
    """Wraps every operation that the runtime performs on a server.

    An interceptor receives the operation context and a `call_next` function, and
    must return the result of `await call_next()`, return another result, or raise.
    Interceptors run in order, inside the concurrency limits and outside the circuit
    breaker, so they observe each operation once, however many attempts it takes.

    The runtime also accepts a plain async function with the same signature; see
    `InterceptorLike`.

    Example:
        ```python
        class Audit(Interceptor):
            async def __call__(self, context: OperationContext, call_next: CallNext):
                print(f"{context.operation} on {context.server_id}")
                return await call_next()
        ```
    """

    @abstractmethod
    async def __call__(self, context: OperationContext, call_next: CallNext, /) -> Any:
        """Run the operation by awaiting `call_next()`, and return its result."""


type InterceptorFunction = Callable[[OperationContext, CallNext], Awaitable[Any]]
"""An async function that wraps an operation like `Interceptor.__call__`."""

type InterceptorLike = Interceptor | InterceptorFunction
"""An `Interceptor` instance or an async function with the same signature."""
