from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from refresh_engine import RefreshConfig, RefreshMode

from mcp_capability_router import ConfigurationError, RefreshPolicy


def test_defaults_are_lazy() -> None:
    policy = RefreshPolicy()
    assert not policy.on_register
    assert not policy.on_query_miss
    assert policy.interval is None
    assert policy.change_events is None
    assert policy.mode is None
    assert policy.event_handlers == ()


async def test_accepts_queues_async_iterables_and_mode_names() -> None:
    async def events() -> AsyncIterator[str]:
        yield "changed"

    queue: asyncio.Queue[str] = asyncio.Queue()
    assert RefreshPolicy(change_events=queue).change_events is queue
    RefreshPolicy(change_events=events())
    policy = RefreshPolicy(
        interval=0.5,
        mode="full",  # type: ignore[arg-type]
        config=RefreshConfig(max_concurrency=2),
        event_handlers=[print],  # type: ignore[arg-type]
    )
    assert policy.mode is RefreshMode.FULL
    assert policy.event_handlers == (print,)


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan"), True, "5"])
def test_rejects_invalid_intervals(interval: object) -> None:
    with pytest.raises(ConfigurationError, match="interval"):
        RefreshPolicy(interval=interval)  # type: ignore[arg-type]


def test_rejects_invalid_values() -> None:
    with pytest.raises(ConfigurationError, match="change_events"):
        RefreshPolicy(change_events=[1, 2])  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="unknown refresh mode"):
        RefreshPolicy(mode="sometimes")  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="TARGETED"):
        RefreshPolicy(mode=RefreshMode.TARGETED)
    with pytest.raises(ConfigurationError, match="not callable"):
        RefreshPolicy(event_handlers=(42,))  # type: ignore[arg-type]
