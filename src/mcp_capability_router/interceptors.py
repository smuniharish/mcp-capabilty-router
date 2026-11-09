"""Interceptors that ship with the router."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from abc import ABC, abstractmethod
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from langchain_core.messages import ToolMessage

from .contracts import CallNext, Interceptor, Operation, OperationContext
from .errors import ConfigurationError
from .models import Tool

if TYPE_CHECKING:
    from collections.abc import Callable


class ResultCacheStore(ABC):
    """Stores the cached results of `ToolResultCache`.

    `InMemoryResultCacheStore` is the default. Subclass it to share cached results
    between processes, for example in Redis; the store decides how to serialize
    the results. Keys start with the server ID followed by a colon.
    """

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Return the unexpired result stored under `key`, or `None`."""

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: float) -> None:
        """Store `value` under `key` for `ttl` seconds."""

    @abstractmethod
    async def clear(self, prefix: str = "") -> None:
        """Remove every result whose key starts with `prefix`."""

    async def close(self) -> None:  # noqa: B027
        """Release the resources of the store; does nothing by default."""


class InMemoryResultCacheStore(ResultCacheStore):
    """Keeps cached results in memory, evicting the least recently used first."""

    def __init__(self, *, max_entries: int = 1024) -> None:
        """Create a store of at most `max_entries` results.

        Raises:
            ConfigurationError: If `max_entries` is not a positive integer.
        """
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            msg = f"max_entries must be a positive integer, got {max_entries!r}"
            raise ConfigurationError(msg)
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def __len__(self) -> int:
        """Return the number of stored results, including expired ones."""
        return len(self._entries)

    async def get(self, key: str) -> Any | None:
        """Return the unexpired result stored under `key`, or `None`."""
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires, value = entry
        if time.monotonic() >= expires:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, ttl: float) -> None:
        """Store `value` under `key` for `ttl` seconds."""
        self._entries[key] = (time.monotonic() + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    async def clear(self, prefix: str = "") -> None:
        """Remove every result whose key starts with `prefix`."""
        if not prefix:
            self._entries.clear()
            return
        for key in [key for key in self._entries if key.startswith(prefix)]:
            del self._entries[key]


def _read_only(tool: Tool) -> bool:
    return tool.read_only


class ToolResultCache(Interceptor):
    """Caches the results of read-only tool calls.

    A call is cached when its tool is selected by `cacheable`, by default the
    tools whose server marks them `readOnlyHint`, and its arguments serialize to
    JSON. Identical calls, the same tool and the same arguments, return the cached
    result until it expires; concurrent identical calls share one server call.
    Errors and `None` results are not cached. A cached `ToolMessage` is returned
    with a new `tool_call_id`.

    Add it to the runtime's interceptors; it runs before the circuit breaker, so a
    cached result is returned even while the server is unavailable.

    Example:
        ```python
        runtime = MCPRuntime(interceptors=[ToolResultCache(ttl=60)])
        ```
    """

    def __init__(
        self,
        *,
        ttl: float = 300.0,
        store: ResultCacheStore | None = None,
        cacheable: Callable[[Tool], bool] | None = None,
    ) -> None:
        """Create a cache.

        Args:
            ttl: How long a result stays cached, in seconds.
            store: Where results are kept; an `InMemoryResultCacheStore` when
                `None`.
            cacheable: Selects the tools whose results are cached; the read-only
                tools when `None`.

        Raises:
            ConfigurationError: If an argument is invalid.
        """
        if isinstance(ttl, bool) or not isinstance(ttl, int | float) or not ttl > 0:
            msg = f"ttl must be a positive number of seconds, got {ttl!r}"
            raise ConfigurationError(msg)
        if store is not None and not isinstance(store, ResultCacheStore):
            msg = f"store {store!r} does not subclass ResultCacheStore"
            raise ConfigurationError(msg)
        if cacheable is not None and not callable(cacheable):
            msg = f"cacheable {cacheable!r} is not callable"
            raise ConfigurationError(msg)
        self._ttl = float(ttl)
        self._store = store if store is not None else InMemoryResultCacheStore()
        self._cacheable = cacheable if cacheable is not None else _read_only
        self._pending: dict[str, asyncio.Future[Any]] = {}

    @property
    def store(self) -> ResultCacheStore:
        """The store that keeps the cached results."""
        return self._store

    async def invalidate(self, server_id: str | None = None) -> None:
        """Drop the cached results of one server, or of every server."""
        await self._store.clear(f"{server_id}:" if server_id is not None else "")

    async def __call__(self, context: OperationContext, call_next: CallNext, /) -> Any:
        """Return the cached result of the call, or make the call and cache it."""
        key = self._key(context)
        if key is None:
            return await call_next()
        cached = await self._store.get(key)
        if cached is not None:
            return _fresh(cached)
        pending = self._pending.get(key)
        if pending is not None:
            try:
                return _fresh(await asyncio.shield(pending))
            except asyncio.CancelledError:
                if not pending.cancelled():
                    raise
                # The call being shared was cancelled, not this one.
                return await call_next()
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[key] = future
        try:
            result = await call_next()
        except Exception as error:
            future.set_exception(error)
            # The waiters re-raise it; the future must not report it as unretrieved.
            future.exception()
            raise
        except BaseException:
            future.cancel()
            raise
        else:
            future.set_result(result)
            if result is not None:
                await self._store.set(key, result, self._ttl)
            return result
        finally:
            del self._pending[key]

    def _key(self, context: OperationContext) -> str | None:
        tool = context.capability
        if (
            context.operation is not Operation.CALL_TOOL
            or not isinstance(tool, Tool)
            or not self._cacheable(tool)
        ):
            return None
        try:
            arguments = json.dumps(
                dict(context.arguments or {}), sort_keys=True, separators=(",", ":")
            )
        except (TypeError, ValueError):
            return None
        digest = hashlib.sha256(arguments.encode()).hexdigest()
        return f"{tool.server_id}:{tool.capability_id}:{digest}"


def _fresh(result: Any) -> Any:
    if isinstance(result, ToolMessage):
        return result.model_copy(update={"tool_call_id": f"call_{uuid.uuid4().hex}"})
    return result
