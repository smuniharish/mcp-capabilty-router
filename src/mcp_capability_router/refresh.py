"""Policies for refreshing the capabilities of a server automatically."""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterable
from dataclasses import dataclass
from typing import Any

from refresh_engine import EventHandler, RefreshConfig, RefreshMode

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
            server, such as `refresh_engine.StructlogEventHandler`.

    Each registration keeps the fingerprints of its last refresh in memory, so
    the first refresh of a registration stores every capability, and later
    refreshes write only what changed. A policy can be shared by several servers.
    """

    on_register: bool = False
    on_query_miss: bool = False
    interval: float | None = None
    change_events: RefreshEventSource | None = None
    mode: RefreshMode | None = None
    config: RefreshConfig | None = None
    event_handlers: tuple[EventHandler, ...] = ()

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
            msg = (
                f"interval must be a positive number of seconds, got {self.interval!r}"
            )
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
            if not callable(handler):
                msg = f"event handler {handler!r} is not callable"
                raise ConfigurationError(msg)
        object.__setattr__(self, "event_handlers", handlers)
