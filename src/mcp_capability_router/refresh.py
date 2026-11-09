"""Policies for refreshing the capabilities of a server automatically."""

from __future__ import annotations

import asyncio
import inspect
import math
from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Any

from refresh_engine import (
    EventHandler,
    EventHandlerLike,
    EventPublisher,
    FingerprintStrategy,
    RefreshConfig,
    RefreshMode,
    StateStore,
)

from .errors import ConfigurationError

type RefreshEventSource = asyncio.Queue[Any] | AsyncIterable[Any]
"""A source of change notifications: an `asyncio.Queue` or any async iterable."""


@dataclass(frozen=True, slots=True, kw_only=True)
class RefreshPolicy:
    """When and how the runtime refreshes the capabilities of one server.

    Without a policy, registration is lazy and capabilities are refreshed only when
    the application calls `MCPRuntime.refresh_server`, `MCPRuntime.refresh`, or
    `MCPRuntime.query` with `refresh_servers`.

    Attributes:
        on_register: Refresh before `register_server` returns. A failure of this
            refresh fails the registration.
        on_query_miss: Refresh when `MCPRuntime.query` finds no match.
        interval: Refresh every `interval` seconds on a fixed schedule.
        change_events: Refresh whenever an item arrives. Items that arrive in a
            burst while a refresh runs trigger one more refresh, not one each.
        mode: The refresh mode of automatic refreshes. `None` lets refresh-engine
            refresh only what changed (`INCREMENTAL`). `TARGETED` is not allowed,
            because automatic refreshes have no targets.
        config: Concurrency, overlap, failure, retry, and timeout settings of the
            server's `refresh_engine.RefreshEngine`; refresh-engine's defaults when
            `None`.
        event_handlers: Handlers that receive the refresh lifecycle events of the
            server: `refresh_engine.EventHandler` instances, such as
            `refresh_engine.StructlogEventHandler`, or async functions.
        state_store: Where the server's refresh state, the fingerprints of its
            capabilities, is kept. Takes precedence over the runtime's
            `state_store_factory`. When neither is set, the state lives in memory.
            A durable store lets a restarted process skip capabilities that did not
            change. A store holds the state of one server, so it cannot be used by
            two registered servers at once.
        fingerprint: How capabilities are fingerprinted to detect changes;
            refresh-engine's `CompositeHash` when `None`.
        events: The publisher that delivers the server's refresh events, for
            example one shared with the rest of the application; a new
            `refresh_engine.AsyncEventPublisher` when `None`. The runtime subscribes
            `event_handlers` and its metrics handler to it, and unsubscribes them
            when the server is unregistered.

    Without a state store, each registration keeps the fingerprints of its last
    refresh in memory, so the first refresh of a registration stores every
    capability, and later refreshes write only what changed. A policy without a
    state store can be shared by several servers.
    """

    on_register: bool = False
    on_query_miss: bool = False
    interval: float | None = None
    change_events: RefreshEventSource | None = None
    mode: RefreshMode | None = None
    config: RefreshConfig | None = None
    event_handlers: tuple[EventHandlerLike, ...] = ()
    state_store: StateStore | None = None
    fingerprint: FingerprintStrategy | None = None
    events: EventPublisher | None = None

    def __post_init__(self) -> None:
        """Validate the policy.

        Raises:
            ConfigurationError: If a value is invalid.
        """
        if self.interval is not None and (
            isinstance(self.interval, bool)
            or not isinstance(self.interval, int | float)
            or not math.isfinite(self.interval)
            or self.interval <= 0
        ):
            msg = f"interval must be a positive number of seconds, got {self.interval!r}"
            raise ConfigurationError(msg)
        if self.change_events is not None and not isinstance(
            self.change_events, asyncio.Queue | AsyncIterable
        ):
            msg = (
                "change_events must be an asyncio.Queue or an async iterable, got "
                f"{type(self.change_events).__name__}"
            )
            raise ConfigurationError(msg)
        if self.mode is not None:
            try:
                mode = RefreshMode(self.mode)
            except ValueError as error:
                msg = f"unknown refresh mode {self.mode!r}"
                raise ConfigurationError(msg) from error
            if mode is RefreshMode.TARGETED:
                msg = "automatic refreshes cannot use RefreshMode.TARGETED"
                raise ConfigurationError(msg)
            object.__setattr__(self, "mode", mode)
        handlers = tuple(self.event_handlers)
        for handler in handlers:
            if not isinstance(handler, EventHandler) and not inspect.iscoroutinefunction(handler):
                msg = (
                    f"event handler {handler!r} must subclass refresh_engine.EventHandler "
                    "or be an async function"
                )
                raise ConfigurationError(msg)
        object.__setattr__(self, "event_handlers", handlers)
        if self.config is not None and not isinstance(self.config, RefreshConfig):
            msg = f"config must be a refresh_engine.RefreshConfig, got {self.config!r}"
            raise ConfigurationError(msg)
        if self.state_store is not None and not isinstance(self.state_store, StateStore):
            msg = f"state_store {self.state_store!r} does not subclass refresh_engine.StateStore"
            raise ConfigurationError(msg)
        if self.fingerprint is not None and not isinstance(self.fingerprint, FingerprintStrategy):
            msg = (
                f"fingerprint {self.fingerprint!r} does not subclass "
                "refresh_engine.FingerprintStrategy"
            )
            raise ConfigurationError(msg)
        if self.events is not None and not isinstance(self.events, EventPublisher):
            msg = f"events {self.events!r} does not subclass refresh_engine.EventPublisher"
            raise ConfigurationError(msg)
