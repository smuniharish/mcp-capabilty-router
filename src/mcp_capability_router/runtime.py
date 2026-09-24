from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from aiolimiter import AsyncLimiter
from refresh_engine import AsyncScheduler, RefreshEngine, RefreshMode, RefreshResult, RefreshStatus
from tenacity import AsyncRetrying

from .errors import CapabilityNotFoundError, RefreshError, ServerError
from .interceptor import Interceptor
from .loader import CapabilityLoader
from .models import Capability, CapabilityType
from .pipeline import OperationPipeline
from .refresh import RefreshEventSource, RefreshPolicy, build_refresh_engine
from .registry import CapabilityRegistry, InMemoryRegistry
from .resilience import MetricsHook
from .retrieval import CapabilityRetriever, DeterministicRetriever
from .server import HealthState, ServerHandle

logger = logging.getLogger(__name__)


class MCPRuntime:
    """Owns all mutable state for one isolated MCP capability runtime."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry | None = None,
        retriever: CapabilityRetriever | None = None,
        max_concurrency: int = 16,
        operation_timeout: float | None = None,
        retry: AsyncRetrying | None = None,
        rate_limiter: AsyncLimiter | None = None,
        interceptors: Iterable[Interceptor[Any]] = (),
        metrics: MetricsHook | None = None,
    ):
        """Configure the runtime.

        ``retry``/``rate_limiter`` accept ``tenacity.AsyncRetrying``/
        ``aiolimiter.AsyncLimiter`` instances directly -- construct these from those
        libraries' own primitives for full control over backoff/rate-limiting
        behavior.
        """
        self.registry = registry or InMemoryRegistry()
        self.retriever = retriever or DeterministicRetriever()
        self._servers: dict[str, ServerHandle] = {}
        self._server_lock = asyncio.Lock()
        self._refresh_engines: dict[str, RefreshEngine] = {}
        self._refresh_policies: dict[str, RefreshPolicy] = {}
        self._refresh_policy_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._refresh_schedulers: dict[str, AsyncScheduler] = {}
        self._loader = CapabilityLoader()
        self._pipeline = OperationPipeline(
            max_concurrency=max_concurrency,
            operation_timeout=operation_timeout,
            retry=retry,
            rate_limiter=rate_limiter,
            interceptors=interceptors,
            metrics=metrics,
        )
        self._closed = False

    async def __aenter__(self) -> MCPRuntime:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def register_server(
        self,
        server_id: str,
        factory: Any,
        *,
        metadata: dict[str, Any] | None = None,
        refresh: RefreshPolicy | None = None,
    ) -> ServerHandle:
        if self._closed:
            raise ServerError("Runtime is closed")
        policy = refresh or RefreshPolicy()
        async with self._server_lock:
            if server_id in self._servers:
                raise ServerError(f"Server already registered: {server_id}")
            handle = ServerHandle(server_id, factory, metadata or {})
            self._servers[server_id] = handle
            self._refresh_policies[server_id] = policy
            self._refresh_engines[server_id] = build_refresh_engine(handle, self.registry, policy)
        try:
            await self._start_refresh_policy(server_id, policy)
        except BaseException:
            await self.unregister_server(server_id)
            raise
        return handle

    async def register_mcp_client(
        self,
        server_id: str,
        client: Any,
        *,
        client_server_name: str | None = None,
        discover_resources: bool = False,
        metadata: dict[str, Any] | None = None,
        refresh: RefreshPolicy | None = None,
    ) -> ServerHandle:
        """Register a ``langchain-mcp-adapters`` client without exposing a bridge class."""
        from .integrations import LangChainMCPAdapter

        adapter = LangChainMCPAdapter(
            client,
            client_server_name or server_id,
            discover_resources=discover_resources,
        )
        return await self.register_server(
            server_id,
            lambda: adapter,
            metadata=metadata,
            refresh=refresh,
        )

    async def unregister_server(self, server_id: str) -> None:
        await self._stop_refresh_policy(server_id)
        async with self._server_lock:
            handle = self._servers.pop(server_id, None)
        if handle is None:
            return
        engine = self._refresh_engines.pop(server_id, None)
        if engine is not None:
            await engine.close()
        await handle.close()
        await self.registry.remove_missing(server_id, set())
        await self._loader.invalidate_server(server_id)
        self._pipeline.reset(server_id)

    async def _start_refresh_policy(self, server_id: str, policy: RefreshPolicy) -> None:
        if policy.on_register:
            await self.refresh_server(server_id, mode=policy.mode)
        if policy.interval is not None:
            scheduler = AsyncScheduler(
                lambda: self._background_refresh(server_id, "interval", policy.mode),
                policy.interval,
            )
            self._refresh_schedulers[server_id] = scheduler
            await scheduler.start()
        if policy.change_events is not None:
            self._refresh_policy_tasks[(server_id, "events")] = asyncio.create_task(
                self._run_event_refresh(server_id, policy.change_events, policy.mode),
                name=f"mcp-refresh-events:{server_id}",
            )

    async def _stop_refresh_policy(self, server_id: str) -> None:
        self._refresh_policies.pop(server_id, None)
        scheduler = self._refresh_schedulers.pop(server_id, None)
        if scheduler is not None:
            await scheduler.stop()
        tasks = [
            self._refresh_policy_tasks.pop(key)
            for key in list(self._refresh_policy_tasks)
            if key[0] == server_id
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_event_refresh(
        self, server_id: str, events: RefreshEventSource, mode: RefreshMode
    ) -> None:
        if isinstance(events, asyncio.Queue):
            while True:
                await events.get()
                await self._background_refresh(server_id, "event", mode)
        else:
            async for _ in events:
                await self._background_refresh(server_id, "event", mode)

    async def _background_refresh(self, server_id: str, trigger: str, mode: RefreshMode) -> None:
        try:
            await self.refresh_server(server_id, mode=mode)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Automatic %s refresh failed for MCP server %r",
                trigger,
                server_id,
            )

    async def connect(self, server_id: str) -> ServerHandle:
        handle = await self._server(server_id)
        await self._run(server_id, "connect", handle.connect)
        return handle

    async def reconnect(self, server_id: str) -> ServerHandle:
        handle = await self._server(server_id)
        await handle.close()
        await handle.connect()
        return handle

    async def refresh_server(
        self,
        server_id: str,
        *,
        mode: RefreshMode = RefreshMode.FULL,
        resource_ids: Iterable[str] = (),
    ) -> RefreshResult:
        """Refresh one server's capabilities via its ``refresh_engine.RefreshEngine``.

        Raises :class:`RefreshError` if the refresh fails outright (e.g. discovery
        could not connect at all). Per-resource failures under refresh-engine's default
        ``FailurePolicy.BEST_EFFORT`` do not raise -- they are reported as a ``PARTIAL``
        status on the returned :class:`refresh_engine.RefreshResult`, which callers can
        inspect via ``result.errors`` for fine-grained per-capability failure detail.
        """
        await self._server(server_id)
        engine = self._refresh_engines[server_id]
        ids = frozenset(resource_ids)

        async def _do_refresh() -> RefreshResult:
            result = await engine.refresh(mode=mode, resource_ids=ids)
            if result.status is RefreshStatus.FAILED:
                message = "; ".join(issue.message for issue in result.errors)
                raise RefreshError(
                    f"Refresh failed for server {server_id!r}: {message or 'unknown error'}"
                )
            return result

        return await self._run(server_id, "discover", _do_refresh)

    async def refresh(self) -> None:
        await asyncio.gather(*(self.refresh_server(server_id) for server_id in self._servers))

    async def retrieve(
        self,
        query: str,
        *,
        type: CapabilityType | None = None,
        limit: int = 20,
        server_id: str | None = None,
    ) -> list[Capability]:
        candidates = await self.registry.list(server_id=server_id, type=type)
        return await self.retriever.retrieve(query, candidates, limit=limit)

    async def query(
        self,
        query: str,
        *,
        type: CapabilityType | None = None,
        limit: int = 20,
        refresh_servers: Iterable[str] = (),
        mode: RefreshMode = RefreshMode.FULL,
        resource_ids: Iterable[str] = (),
    ) -> list[Capability]:
        """Retrieve, optionally refreshing only the servers relevant to the query."""
        candidates = await self.retrieve(query, type=type, limit=limit)
        if candidates:
            return candidates
        servers = set(refresh_servers)
        servers.update(
            server_id
            for server_id, policy in self._refresh_policies.items()
            if policy.on_query_miss
        )
        if servers:
            await asyncio.gather(
                *(
                    self.refresh_server(server_id, mode=mode, resource_ids=resource_ids)
                    for server_id in servers
                )
            )
            return await self.retrieve(query, type=type, limit=limit)
        return []

    async def resolve(self, capability_id: str) -> Capability:
        capability = await self.registry.get(capability_id)
        if capability is None:
            raise CapabilityNotFoundError(capability_id)
        return capability

    async def load(self, capability_id: str) -> Any:
        capability = await self.resolve(capability_id)
        return await self._loader.load(capability, await self.connect(capability.server_id))

    async def execute(self, capability_id: str, arguments: dict[str, Any] | None = None) -> Any:
        capability = await self.resolve(capability_id)
        if capability.type != CapabilityType.TOOL:
            raise ServerError(f"{capability_id} is not a tool")
        handle = await self.connect(capability.server_id)
        assert handle.adapter is not None
        return await self._run(
            capability.server_id,
            "call_tool",
            lambda: handle.adapter.call_tool(capability.name, arguments),
        )

    async def read_resource(self, capability_id: str) -> Any:
        capability = await self.resolve(capability_id)
        if capability.type != CapabilityType.RESOURCE:
            raise ServerError(f"{capability_id} is not a resource")
        handle = await self.connect(capability.server_id)
        assert handle.adapter is not None
        return await self._run(
            capability.server_id,
            "read_resource",
            lambda: handle.adapter.read_resource(
                getattr(capability, "uri", None) or capability.name
            ),
        )

    async def get_prompt(self, capability_id: str, arguments: dict[str, Any] | None = None) -> Any:
        capability = await self.resolve(capability_id)
        if capability.type != CapabilityType.PROMPT:
            raise ServerError(f"{capability_id} is not a prompt")
        handle = await self.connect(capability.server_id)
        assert handle.adapter is not None
        return await self._run(
            capability.server_id,
            "get_prompt",
            lambda: handle.adapter.get_prompt(capability.name, arguments),
        )

    async def _run(
        self,
        server_id: str,
        operation: str,
        action: Any,
    ) -> Any:
        """Run an MCP operation through the runtime-scoped resilience pipeline.

        Every operation -- ``connect``, ``discover``, ``call_tool``, ``read_resource``,
        and ``get_prompt`` -- is funneled through this single choke point, so timeout,
        retry, circuit breaker, rate limiting, bulkhead admission, metrics, and health
        tracking are applied uniformly and only ever scoped to this runtime instance.
        """
        handle = await self._server(server_id)
        try:
            result = await self._pipeline.run(server_id, operation, action)
        except BaseException as error:
            if not isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                handle.health = HealthState(await self._pipeline.health(server_id))
            raise
        handle.health = HealthState(await self._pipeline.health(server_id))
        return result

    async def health(self, server_id: str) -> HealthState:
        return (await self._server(server_id)).health

    async def _server(self, server_id: str) -> ServerHandle:
        async with self._server_lock:
            handle = self._servers.get(server_id)
        if handle is None:
            raise ServerError(f"Unknown server: {server_id}")
        return handle

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        tasks = list(self._refresh_policy_tasks.values())
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        schedulers = list(self._refresh_schedulers.values())
        await asyncio.gather(
            *(scheduler.stop() for scheduler in schedulers), return_exceptions=True
        )
        engines = list(self._refresh_engines.values())
        await asyncio.gather(*(engine.close() for engine in engines), return_exceptions=True)
        handles = list(self._servers.values())
        await asyncio.gather(*(handle.close() for handle in handles), return_exceptions=True)
        await self.registry.close()
        await self._loader.close()
        self._servers.clear()
        self._refresh_policies.clear()
        self._refresh_policy_tasks.clear()
        self._refresh_schedulers.clear()
        self._refresh_engines.clear()
