"""The capability routing runtime."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self

import refresh_engine
from refresh_engine import (
    AsyncEventPublisher,
    AsyncScheduler,
    EventHandlerLike,
    EventPublisher,
    MetricsEventHandler,
    MetricsSink,
    RefreshEngine,
    RefreshMode,
    RefreshResult,
    RefreshStatus,
    ResourceSelector,
    StateStore,
    TriggerSource,
)

from ._internal.discovery import discover_capabilities
from ._internal.metrics import ServerScopedSink
from ._internal.naming import validate_limit, validate_server_id
from ._internal.pipeline import OperationPipeline
from ._internal.servers import ServerHandle
from ._internal.sources import CapabilitySource, RegistryOperation
from ._internal.tools import capability_tool
from .adapters import FastMCPAdapter, FastMCPTarget
from .contracts import (
    AdapterFactory,
    CapabilityRegistry,
    CapabilityRetriever,
    InterceptorLike,
    MCPAdapter,
    Operation,
    OperationContext,
)
from .errors import (
    CapabilityNotFoundError,
    CapabilityTypeError,
    ConfigurationError,
    InvalidRequestError,
    RefreshError,
    RuntimeClosedError,
    ServerConnectionError,
    ServerNotFoundError,
)
from .models import Capability, CapabilityType, HealthState, Prompt, Resource, Tool
from .refresh import RefreshEventSource, RefreshPolicy
from .registry import InMemoryRegistry
from .resilience import ResiliencePolicy
from .retrieval import KeywordRetriever

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

logger = logging.getLogger("mcp_capability_router")

type StateStoreFactory = Callable[[str], StateStore | Awaitable[StateStore]]
"""Creates the refresh state store of a server from its ID; may be async."""

type CapabilityFilter = Callable[[Capability], bool]
"""Decides whether a capability may be retrieved."""


@dataclass(slots=True)
class _Server:
    """A registered server and everything that its registration owns.

    The entry stays in `MCPRuntime._servers`, reserving its ID, until it is
    disposed. It is `active` until an unregistration or a shutdown begins. The
    lock serializes the setup of the registration with its disposal.
    """

    handle: ServerHandle
    policy: RefreshPolicy
    source: CapabilitySource
    engine: RefreshEngine
    stack: contextlib.AsyncExitStack
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    active: bool = True
    disposed: bool = False


async def _cancel(task: asyncio.Task[None]) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def _unsubscribe(publisher: EventPublisher, handler: EventHandlerLike) -> None:
    with contextlib.suppress(Exception):
        publisher.unsubscribe(handler)


class MCPRuntime:
    """Discovers, retrieves, and invokes the capabilities of MCP servers.

    A runtime owns everything it creates — the servers and their connections, the
    default registry, retrieval caches, circuit breakers, schedulers, and
    background tasks — and shares none of it with other runtimes. Create one
    runtime per tenant, agent, or trust boundary, and close it with `close` or
    `async with`.

    Registering a server stores a factory, not a connection. Discovery lists
    capability metadata into the registry; retrieval ranks that metadata without
    calling any server; a server is connected only when an operation needs it.
    Every operation on a server runs through one resilience pipeline: concurrency
    limits, interceptors, a circuit breaker per server and operation, retries,
    rate limiting, and a timeout per attempt.

    Example:
        ```python
        async with MCPRuntime() as runtime:
            await runtime.register_mcp("docs", "https://example.com/mcp")
            await runtime.refresh_server("docs")
            [tool] = await runtime.retrieve("search the docs", limit=1)
            result = await runtime.execute(tool.capability_id, {"query": "routing"})
        ```
    """

    def __init__(
        self,
        *,
        registry: CapabilityRegistry | None = None,
        retriever: CapabilityRetriever | None = None,
        max_concurrency: int = 16,
        resilience: ResiliencePolicy | None = None,
        interceptors: Iterable[InterceptorLike] = (),
        metrics: MetricsSink | None = None,
        state_store_factory: StateStoreFactory | None = None,
    ) -> None:
        """Create a runtime.

        Args:
            registry: Where capability metadata is stored; an `InMemoryRegistry`
                when `None`. The runtime closes it when it closes.
            retriever: How capabilities are ranked; a `KeywordRetriever` when
                `None`.
            max_concurrency: The maximum number of server operations that run at
                the same time, across all servers.
            resilience: The timeouts, retries, rate limit, circuit breakers, and
                per-server concurrency of every server registered without its own
                policy; no timeout, a single attempt, and in-memory circuit
                breakers per server when `None`.
            interceptors: `Interceptor` instances or async functions that wrap
                every server operation, in order.
            metrics: A refresh-engine metrics sink that receives the counters and
                durations of server operations and refreshes.
            state_store_factory: Creates the refresh state store of each server
                registered without a `RefreshPolicy.state_store`, called with the
                server ID at registration. It may be an async function. The state
                lives in memory when `None`.

        Raises:
            ConfigurationError: If an argument is invalid.
        """
        if registry is not None and not isinstance(registry, CapabilityRegistry):
            msg = f"registry {registry!r} does not subclass CapabilityRegistry"
            raise ConfigurationError(msg)
        if retriever is not None and not isinstance(retriever, CapabilityRetriever):
            msg = f"retriever {retriever!r} does not subclass CapabilityRetriever"
            raise ConfigurationError(msg)
        if metrics is not None and not isinstance(metrics, MetricsSink):
            msg = f"metrics {metrics!r} does not subclass refresh_engine.MetricsSink"
            raise ConfigurationError(msg)
        if state_store_factory is not None and not callable(state_store_factory):
            msg = f"state_store_factory {state_store_factory!r} is not callable"
            raise ConfigurationError(msg)
        self._registry: CapabilityRegistry = (
            registry if registry is not None else InMemoryRegistry()
        )
        self._retriever: CapabilityRetriever = (
            retriever if retriever is not None else KeywordRetriever()
        )
        self._pipeline = OperationPipeline(
            max_concurrency=max_concurrency,
            policy=resilience if resilience is not None else ResiliencePolicy(),
            interceptors=interceptors,
            metrics_sink=metrics,
        )
        self._metrics = metrics
        self._state_store_factory = state_store_factory
        self._stores: dict[int, str] = {}
        self._servers: dict[str, _Server] = {}
        self._closed = False

    async def __aenter__(self) -> Self:
        """Return the runtime."""
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Close the runtime."""
        await self.close()

    @property
    def registry(self) -> CapabilityRegistry:
        """The registry that stores capability metadata."""
        return self._registry

    @property
    def retriever(self) -> CapabilityRetriever:
        """The retriever that ranks capabilities."""
        return self._retriever

    @property
    def resilience(self) -> ResiliencePolicy:
        """The resilience policy of servers registered without their own."""
        return self._pipeline.policy

    @property
    def servers(self) -> tuple[str, ...]:
        """The IDs of the registered servers, in registration order."""
        return tuple(name for name, server in self._servers.items() if server.active)

    @property
    def closed(self) -> bool:
        """Whether the runtime is closed."""
        return self._closed

    async def register_server(
        self,
        server_id: str,
        factory: AdapterFactory,
        *,
        refresh: RefreshPolicy | None = None,
        resilience: ResiliencePolicy | None = None,
    ) -> None:
        """Register a server without connecting to it.

        Args:
            server_id: A unique ID of 1 to 64 letters, digits, hyphens, or
                underscores, starting with a letter or digit.
            factory: Creates the adapter of the server; it may be an async
                function. It is called on first use, and again after `reconnect`
                or a lost connection.
            refresh: When and how to refresh the capabilities of the server,
                including its refresh state store and event publisher.
            resilience: The resilience policy of the server; the runtime's
                `resilience` when `None`.

        Raises:
            ConfigurationError: If an argument is invalid, the ID is taken by a
                registered server or one that is still being unregistered, or the
                state store is used by another registered server.
            RefreshError: If `refresh.on_register` is set and the refresh fails;
                the server is not registered then.
            ServerNotFoundError: If the server was unregistered before its
                registration completed.
            RuntimeClosedError: If the runtime is closed, including while the
                registration was in progress.
        """
        self._ensure_open()
        validate_server_id(server_id)
        if not callable(factory):
            msg = f"the adapter factory of server {server_id!r} is not callable"
            raise ConfigurationError(msg)
        policy = refresh if refresh is not None else RefreshPolicy()
        if not isinstance(policy, RefreshPolicy):
            msg = f"refresh must be a RefreshPolicy, got {type(policy).__name__}"
            raise ConfigurationError(msg)
        if resilience is not None and not isinstance(resilience, ResiliencePolicy):
            msg = f"resilience must be a ResiliencePolicy, got {type(resilience).__name__}"
            raise ConfigurationError(msg)
        self._ensure_available(server_id)
        store = await self._state_store(server_id, policy)
        self._ensure_open()
        self._ensure_available(server_id)
        if store is not None and id(store) in self._stores:
            msg = (
                f"the state store of server {server_id!r} is used by server "
                f"{self._stores[id(store)]!r}; give each server its own store"
            )
            raise ConfigurationError(msg)
        handle = ServerHandle(server_id, factory)
        source = CapabilitySource(
            functools.partial(self._discover, handle),
            functools.partial(self._reconcile, server_id, restore=store is not None),
        )
        stack = contextlib.AsyncExitStack()
        try:
            engine = RefreshEngine(
                source,
                RegistryOperation(self.registry),
                fingerprint=policy.fingerprint,
                store=store,
                config=policy.config,
                events=self._event_publisher(server_id, policy, stack),
            )
        except BaseException:
            await stack.aclose()
            raise
        server = _Server(handle, policy, source, engine, stack)
        self._servers[server_id] = server
        if store is not None:
            self._stores[id(store)] = server_id
            stack.callback(self._stores.pop, id(store), None)
        self._pipeline.add_server(server_id, resilience)
        async with server.lock:
            try:
                server.stack.push_async_callback(handle.close)
                await server.stack.enter_async_context(engine)
                if policy.on_register:
                    await self._refresh(server, mode=policy.mode, trigger=TriggerSource.MANUAL)
                    self._ensure_registering(server_id, server)
                if policy.interval is not None:
                    scheduler = AsyncScheduler(
                        functools.partial(
                            self._background_refresh,
                            server_id,
                            TriggerSource.SCHEDULED,
                        ),
                        policy.interval,
                    )
                    await server.stack.enter_async_context(scheduler)
                if policy.change_events is not None:
                    task = asyncio.create_task(
                        self._watch(server_id, policy.change_events),
                        name=f"mcp-capability-router:{server_id}:change-events",
                    )
                    server.stack.push_async_callback(_cancel, task)
                self._ensure_registering(server_id, server)
            except BaseException:
                server.active = False
                try:
                    await self._dispose_locked(server_id, server, forget=True)
                except Exception:
                    logger.exception(
                        "Cleaning up the failed registration of server %r failed",
                        server_id,
                    )
                raise

    async def register_mcp(
        self,
        server_id: str,
        target: FastMCPTarget,
        *,
        refresh: RefreshPolicy | None = None,
        resilience: ResiliencePolicy | None = None,
        **client_options: Any,
    ) -> None:
        """Register an MCP server reached through FastMCP.

        Args:
            server_id: A unique ID; see `register_server`.
            target: A URL, a script path, an MCP configuration dictionary, an
                in-process `FastMCP` server, a transport, or a `fastmcp.Client`
                configured with its own authentication, headers, and handlers.
            refresh: When and how to refresh the capabilities of the server.
            resilience: The resilience policy of the server; the runtime's
                `resilience` when `None`.
            **client_options: Keyword arguments of the `fastmcp.Client` that each
                connection creates, such as `auth`, `timeout`, or
                `sampling_handler`; see `FastMCPAdapter`.

        Raises:
            ConfigurationError: If an argument is invalid or the ID is taken.
            RefreshError: If `refresh.on_register` is set and the refresh fails.
            RuntimeClosedError: If the runtime is closed.
        """
        from fastmcp import Client

        if client_options and isinstance(target, Client):
            msg = (
                "client options cannot be applied to a prebuilt fastmcp.Client; "
                "configure the client instead"
            )
            raise ConfigurationError(msg)
        await self.register_server(
            server_id,
            functools.partial(FastMCPAdapter, target, **client_options),
            refresh=refresh,
            resilience=resilience,
        )

    async def unregister_server(self, server_id: str) -> None:
        """Stop a server's automatic refreshes, close it, and forget its capabilities.

        A registration of the server that is still in progress is undone. The ID
        can be registered again once this method returns. In a registry shared by
        several processes, the capabilities are removed for every process.

        Raises:
            ServerNotFoundError: If no server is registered under `server_id`.
            RuntimeClosedError: If the runtime is closed.
        """
        server = self._server(server_id)
        server.active = False
        await self._dispose(server_id, server, forget=True)

    async def connect(self, server_id: str) -> None:
        """Connect to a server now instead of on first use.

        Raises:
            ServerNotFoundError: If no server is registered under `server_id`.
            RuntimeClosedError: If the runtime is closed.
        """
        handle = self._server(server_id).handle
        await self._pipeline.run(
            OperationContext(server_id=server_id, operation=Operation.CONNECT),
            handle.connect,
        )

    async def reconnect(self, server_id: str) -> None:
        """Close the connection to a server and open a new one.

        Raises:
            ServerNotFoundError: If no server is registered under `server_id`.
            RuntimeClosedError: If the runtime is closed.
        """
        handle = self._server(server_id).handle
        await self._pipeline.run(
            OperationContext(server_id=server_id, operation=Operation.CONNECT),
            handle.reconnect,
        )

    async def refresh_server(
        self,
        server_id: str,
        *,
        mode: RefreshMode | None = None,
        resource_ids: str | Iterable[str] = (),
        selector: ResourceSelector | None = None,
    ) -> RefreshResult:
        """Discover the capabilities of a server and reconcile the registry.

        Args:
            server_id: The server to refresh.
            mode: The refresh mode. When `None`, refresh-engine refreshes what
                changed, or only the targets when `resource_ids` or `selector` is
                given.
            resource_ids: Capability IDs to refresh.
            selector: A refresh-engine selector of the capabilities to refresh.
                Capabilities expose their `type` and `tags` to selectors, as in
                `TagSelector("tool", key="type")`.

        Returns:
            The refresh result. Capabilities that failed to store are reported in
            `result.errors` with status `PARTIAL`, without raising.

        Raises:
            RefreshError: If the refresh failed as a whole, for example because
                discovery failed.
            ConfigurationError: If the arguments are inconsistent.
            ServerNotFoundError: If no server is registered under `server_id`.
            RuntimeClosedError: If the runtime is closed.
        """
        return await self._refresh(
            self._server(server_id),
            mode=mode,
            trigger=TriggerSource.MANUAL,
            resource_ids=resource_ids,
            selector=selector,
        )

    async def refresh(self, *, mode: RefreshMode | None = None) -> dict[str, RefreshResult]:
        """Refresh every registered server concurrently.

        Every refresh runs to completion, even when others fail.

        Args:
            mode: The refresh mode; see `refresh_server`.

        Returns:
            The result of each server, by server ID.

        Raises:
            ExceptionGroup: With one `RefreshError` per failed server, after all
                refreshes completed.
            RuntimeClosedError: If the runtime is closed.
        """
        self._ensure_open()
        servers = {name: server for name, server in self._servers.items() if server.active}
        outcomes = await asyncio.gather(
            *(
                self._refresh(server, mode=mode, trigger=TriggerSource.MANUAL)
                for server in servers.values()
            ),
            return_exceptions=True,
        )
        results: dict[str, RefreshResult] = {}
        errors: list[Exception] = []
        for server_id, outcome in zip(servers, outcomes, strict=True):
            if isinstance(outcome, RefreshResult):
                results[server_id] = outcome
            elif isinstance(outcome, Exception):
                errors.append(outcome)
            else:
                raise outcome
        if errors:
            msg = f"refresh failed for {len(errors)} of {len(servers)} servers"
            raise ExceptionGroup(msg, errors)
        return results

    async def retrieve(
        self,
        query: str,
        *,
        type: CapabilityType | None = None,
        server_id: str | None = None,
        limit: int = 20,
        where: CapabilityFilter | None = None,
        include_unhealthy: bool = False,
    ) -> list[Capability]:
        """Rank the known capabilities against `query`, without calling any server.

        Args:
            query: What the capability should do.
            type: Only consider capabilities of this type.
            server_id: Only consider capabilities of this server.
            limit: The maximum number of capabilities to return.
            where: Only consider capabilities for which it returns `True`, for
                example `lambda c: isinstance(c, Tool) and c.read_only`.
            include_unhealthy: Also consider capabilities of servers whose circuit
                is open. They are left out by default, because calling them fails
                without reaching the server until the circuit recovers.

        Returns:
            The best matches, best first.

        Raises:
            ConfigurationError: If `limit` is not a positive integer.
            ServerNotFoundError: If `server_id` is not registered.
            RuntimeClosedError: If the runtime is closed.
        """
        self._ensure_open()
        validate_limit(limit)
        if server_id is not None:
            self._server(server_id)
        candidates = await self.registry.list(server_id=server_id, type=type)
        if where is not None:
            candidates = [capability for capability in candidates if where(capability)]
        if not include_unhealthy and candidates:
            unhealthy = await self._unhealthy({c.server_id for c in candidates})
            if unhealthy:
                candidates = [c for c in candidates if c.server_id not in unhealthy]
        if not candidates:
            return []
        return await self.retriever.retrieve(query, candidates, limit=limit)

    async def query(
        self,
        query: str,
        *,
        type: CapabilityType | None = None,
        server_id: str | None = None,
        limit: int = 20,
        where: CapabilityFilter | None = None,
        include_unhealthy: bool = False,
        refresh_servers: Iterable[str] = (),
    ) -> list[Capability]:
        """Retrieve, refreshing servers first when nothing matches.

        When retrieval finds no match, the servers named in `refresh_servers` and
        the servers whose policy sets `on_query_miss` are refreshed concurrently,
        and retrieval runs again. When `server_id` is given, only that server is
        refreshed. A failed refresh is logged and does not fail the query.

        Args:
            query: What the capability should do.
            type: Only consider capabilities of this type.
            server_id: Only consider capabilities of this server.
            limit: The maximum number of capabilities to return.
            where: Only consider capabilities for which it returns `True`.
            include_unhealthy: Also consider capabilities of servers whose circuit
                is open.
            refresh_servers: Servers to refresh on a miss, in addition to those
                whose policy sets `on_query_miss`.

        Returns:
            The best matches, best first.

        Raises:
            ConfigurationError: If `limit` is not a positive integer.
            ServerNotFoundError: If `server_id` or a server in `refresh_servers`
                is not registered.
            RuntimeClosedError: If the runtime is closed.
        """
        hinted = {name: self._server(name) for name in refresh_servers}
        retrieve = functools.partial(
            self.retrieve,
            query,
            type=type,
            server_id=server_id,
            limit=limit,
            where=where,
            include_unhealthy=include_unhealthy,
        )
        matches = await retrieve()
        if matches:
            return matches
        targets = hinted | {
            name: server
            for name, server in self._servers.items()
            if server.active and server.policy.on_query_miss
        }
        if server_id is not None:
            targets = {name: s for name, s in targets.items() if name == server_id}
        if not targets:
            return []
        await asyncio.gather(
            *(self._background_refresh(name, TriggerSource.QUERY) for name in targets)
        )
        return await retrieve()

    async def resolve(self, capability_id: str) -> Capability:
        """Return the capability with ID `capability_id`.

        Raises:
            CapabilityNotFoundError: If the registry does not hold it.
            RuntimeClosedError: If the runtime is closed.
        """
        self._ensure_open()
        capability = await self.registry.get(capability_id)
        if capability is None:
            msg = f"no capability {capability_id!r}; refresh its server first"
            raise CapabilityNotFoundError(msg)
        return capability

    async def execute(self, capability_id: str, arguments: Mapping[str, Any] | None = None) -> Any:
        """Call a tool.

        Args:
            capability_id: The ID of the tool.
            arguments: The tool arguments.

        Returns:
            Whatever the adapter returns; a `ToolMessage` for `FastMCPAdapter`.

        Raises:
            CapabilityNotFoundError: If the tool is unknown.
            CapabilityTypeError: If the capability is not a tool.
            CircuitOpenError: If the circuit of the server is open.
            ServerError: If the server operation fails.
            RuntimeClosedError: If the runtime is closed.
        """
        tool = await self._typed(capability_id, Tool)
        values = dict(arguments or {})
        return await self._operate(
            tool,
            Operation.CALL_TOOL,
            values,
            lambda adapter: adapter.call_tool(tool.name, values),
        )

    async def read_resource(self, capability_id: str) -> Any:
        """Read a resource.

        Returns:
            Whatever the adapter returns; the MCP resource contents for
            `FastMCPAdapter`.

        Raises:
            CapabilityNotFoundError: If the resource is unknown.
            CapabilityTypeError: If the capability is not a resource.
            CircuitOpenError: If the circuit of the server is open.
            ServerError: If the server operation fails.
            RuntimeClosedError: If the runtime is closed.
        """
        resource = await self._typed(capability_id, Resource)
        return await self._operate(
            resource,
            Operation.READ_RESOURCE,
            None,
            lambda adapter: adapter.read_resource(resource.uri),
        )

    async def get_prompt(
        self, capability_id: str, arguments: Mapping[str, str] | None = None
    ) -> Any:
        """Render a prompt.

        Required arguments are checked before the server is called.

        Args:
            capability_id: The ID of the prompt.
            arguments: The prompt arguments; MCP prompt arguments are strings.

        Returns:
            Whatever the adapter returns; the MCP `GetPromptResult` for
            `FastMCPAdapter`.

        Raises:
            CapabilityNotFoundError: If the prompt is unknown.
            CapabilityTypeError: If the capability is not a prompt.
            InvalidRequestError: If an argument is missing or not a string.
            CircuitOpenError: If the circuit of the server is open.
            ServerError: If the server operation fails.
            RuntimeClosedError: If the runtime is closed.
        """
        prompt = await self._typed(capability_id, Prompt)
        values = dict(arguments or {})
        missing = [
            argument.name
            for argument in prompt.arguments
            if argument.required and argument.name not in values
        ]
        if missing:
            msg = f"prompt {prompt.name!r} requires the arguments {missing}"
            raise InvalidRequestError(msg)
        invalid = sorted(name for name, value in values.items() if not isinstance(value, str))
        if invalid:
            msg = f"prompt arguments must be strings; {invalid} are not"
            raise InvalidRequestError(msg)
        return await self._operate(
            prompt,
            Operation.GET_PROMPT,
            values,
            lambda adapter: adapter.get_prompt(prompt.name, values),
        )

    async def as_tool(self, capability_id: str, *, name: str | None = None) -> BaseTool:
        """Return a LangChain tool that calls a routed tool through this runtime.

        The tool uses the capability's JSON schema, runs through the resilience
        pipeline, returns the tool content and its structured artifact, and turns
        router errors and timeouts into error tool messages for the model. It is
        asynchronous.

        Args:
            capability_id: The ID of the tool.
            name: The tool name shown to the model; the MCP tool name by default.

        Raises:
            CapabilityNotFoundError: If the tool is unknown.
            CapabilityTypeError: If the capability is not a tool.
            RuntimeClosedError: If the runtime is closed.
        """
        return capability_tool(self, await self._typed(capability_id, Tool), name=name)

    async def health(self, server_id: str) -> HealthState:
        """Return the health of a server, the worst among its circuits.

        Raises:
            ServerNotFoundError: If no server is registered under `server_id`.
            RuntimeClosedError: If the runtime is closed.
        """
        self._server(server_id)
        return await self._pipeline.health(server_id)

    async def close(self) -> None:
        """Stop automatic refreshes, close every server, and close the registry.

        Running refreshes and registrations in progress are awaited; the
        registrations are undone. Capabilities stay in external registries. The
        registry and the circuit breakers are released even if closing the
        servers fails or is cancelled, so bounding the shutdown with
        `async with asyncio.timeout(10): await runtime.close()` still releases
        them. Calling `close` again has no effect.

        Raises:
            ExceptionGroup: If closing some servers or the registry failed; every
                other resource is still closed.
        """
        if self._closed:
            return
        self._closed = True
        servers = list(self._servers.items())
        for _, server in servers:
            server.active = False
        errors: list[BaseException] = []
        try:
            outcomes = await asyncio.gather(
                *(self._dispose(name, server, forget=False) for name, server in servers),
                return_exceptions=True,
            )
            errors.extend(outcome for outcome in outcomes if isinstance(outcome, BaseException))
        finally:
            try:
                await self.registry.close()
            except Exception as error:
                errors.append(error)
            finally:
                await self._pipeline.aclose()
        if errors:
            msg = "errors while closing the runtime"
            raise BaseExceptionGroup(msg, errors)

    def _ensure_open(self) -> None:
        if self._closed:
            msg = "the runtime is closed"
            raise RuntimeClosedError(msg)

    def _server(self, server_id: str) -> _Server:
        self._ensure_open()
        server = self._servers.get(server_id)
        if server is None or not server.active:
            msg = f"no server {server_id!r} is registered"
            raise ServerNotFoundError(msg)
        return server

    async def _unhealthy(self, server_ids: set[str]) -> set[str]:
        ordered = sorted(server_ids)
        states = await asyncio.gather(*(self._pipeline.health(server_id) for server_id in ordered))
        return {
            server_id
            for server_id, state in zip(ordered, states, strict=True)
            if state is HealthState.UNHEALTHY
        }

    def _ensure_registering(self, server_id: str, server: _Server) -> None:
        """Raise if the registration of `server` was undone while in progress."""
        if server.active:
            return
        self._ensure_open()
        msg = f"server {server_id!r} was unregistered while it was being registered"
        raise ServerNotFoundError(msg)

    async def _typed[C: Capability](self, capability_id: str, kind: type[C]) -> C:
        capability = await self.resolve(capability_id)
        if not isinstance(capability, kind):
            msg = f"{capability_id!r} is a {capability.type}, not a {kind.__name__.lower()}"
            raise CapabilityTypeError(msg)
        return capability

    async def _operate[T](
        self,
        capability: Capability,
        operation: Operation,
        arguments: Mapping[str, Any] | None,
        use: Callable[[MCPAdapter], Awaitable[T]],
    ) -> T:
        handle = self._server(capability.server_id).handle
        context = OperationContext(
            server_id=capability.server_id,
            operation=operation,
            capability=capability,
            arguments=arguments,
        )
        return await self._pipeline.run(context, lambda: self._use(handle, use))

    async def _use[T](self, handle: ServerHandle, use: Callable[[MCPAdapter], Awaitable[T]]) -> T:
        adapter = await handle.adapter()
        try:
            return await use(adapter)
        except (ServerConnectionError, ConnectionError):
            await handle.discard(adapter)
            raise

    async def _discover(self, handle: ServerHandle) -> Sequence[Capability]:
        server_id = handle.server_id
        return await self._pipeline.run(
            OperationContext(server_id=server_id, operation=Operation.DISCOVER),
            lambda: self._use(handle, lambda adapter: discover_capabilities(adapter, server_id)),
        )

    async def _refresh(
        self,
        server: _Server,
        *,
        mode: RefreshMode | None,
        trigger: TriggerSource,
        resource_ids: str | Iterable[str] = (),
        selector: ResourceSelector | None = None,
    ) -> RefreshResult:
        server_id = server.handle.server_id
        try:
            result = await server.engine.refresh(
                mode=mode, resource_ids=resource_ids, selector=selector, trigger=trigger
            )
        except refresh_engine.ConfigurationError as error:
            raise ConfigurationError(str(error)) from error
        except refresh_engine.EngineClosedError as error:
            self._ensure_open()
            msg = f"server {server_id!r} was unregistered during the refresh"
            raise ServerNotFoundError(msg) from error
        if result.status is RefreshStatus.FAILED:
            cause = server.source.take_error()
            detail = "; ".join(issue.message for issue in result.errors)
            msg = f"refresh of server {server_id!r} failed: {detail or 'no detail'}"
            raise RefreshError(msg, result) from cause
        return result

    async def _background_refresh(self, server_id: str, trigger: TriggerSource) -> None:
        server = self._servers.get(server_id)
        if server is None or not server.active:
            return
        try:
            await self._refresh(server, mode=server.policy.mode, trigger=trigger)
        except (RefreshError, ServerNotFoundError, RuntimeClosedError) as error:
            logger.warning(
                "Automatic %s refresh of server %r failed: %s",
                trigger,
                server_id,
                error,
            )
        except Exception:
            logger.exception("Automatic %s refresh of server %r failed", trigger, server_id)

    async def _watch(self, server_id: str, events: RefreshEventSource) -> None:
        try:
            if isinstance(events, asyncio.Queue):
                while True:
                    await events.get()
                    received = 1
                    while not events.empty():
                        events.get_nowait()
                        received += 1
                    try:
                        await self._background_refresh(server_id, TriggerSource.EVENT)
                    finally:
                        for _ in range(received):
                            events.task_done()
            else:
                async for _ in events:
                    await self._background_refresh(server_id, TriggerSource.EVENT)
        except Exception:
            logger.exception("The change events of server %r failed", server_id)

    def _ensure_available(self, server_id: str) -> None:
        existing = self._servers.get(server_id)
        if existing is not None:
            state = "registered" if existing.active else "being unregistered"
            msg = f"server {server_id!r} is already {state}"
            raise ConfigurationError(msg)

    async def _state_store(self, server_id: str, policy: RefreshPolicy) -> StateStore | None:
        if policy.state_store is not None:
            return policy.state_store
        if self._state_store_factory is None:
            return None
        store = self._state_store_factory(server_id)
        if inspect.isawaitable(store):
            store = await store
        if not isinstance(store, StateStore):
            msg = (
                f"state_store_factory returned {store!r} for server {server_id!r}, "
                "which does not subclass refresh_engine.StateStore"
            )
            raise ConfigurationError(msg)
        return store

    def _event_publisher(
        self, server_id: str, policy: RefreshPolicy, stack: contextlib.AsyncExitStack
    ) -> EventPublisher | None:
        handlers: list[EventHandlerLike] = list(policy.event_handlers)
        if self._metrics is not None:
            handlers.append(MetricsEventHandler(ServerScopedSink(self._metrics, server_id)))
        if policy.events is None and not handlers:
            return None
        publisher = policy.events if policy.events is not None else AsyncEventPublisher()
        for handler in handlers:
            publisher.subscribe(handler)
            stack.callback(_unsubscribe, publisher, handler)
        return publisher

    async def _reconcile(
        self, server_id: str, discovered: Sequence[Capability], *, restore: bool
    ) -> None:
        """Align the registry with the first discovery of a registration.

        A new registration cannot know which capabilities an earlier one, such as
        a previous process with a durable registry, stored and the server has
        since removed, so they are removed here. With a state store, refresh-engine
        skips the capabilities whose fingerprints it already holds, so the ones
        that the registry lacks, for example after a restart with an in-memory
        registry, are stored here.
        """
        ids = {capability.capability_id for capability in discovered}
        stored = await self.registry.list(server_id=server_id)
        for capability in stored:
            if capability.capability_id not in ids:
                await self.registry.remove(capability.capability_id)
        if restore:
            known = {capability.capability_id for capability in stored}
            missing = [c for c in discovered if c.capability_id not in known]
            if missing:
                await self.registry.upsert_many(missing)

    async def _dispose(self, server_id: str, server: _Server, *, forget: bool) -> None:
        async with server.lock:
            await self._dispose_locked(server_id, server, forget=forget)

    async def _dispose_locked(self, server_id: str, server: _Server, *, forget: bool) -> None:
        if server.disposed:
            return
        server.disposed = True
        try:
            await server.stack.aclose()
        finally:
            self._pipeline.remove_server(server_id)
            try:
                if forget:
                    await self.registry.remove_server(server_id)
            finally:
                # The entry reserved the ID until now; it cannot have been replaced.
                del self._servers[server_id]
