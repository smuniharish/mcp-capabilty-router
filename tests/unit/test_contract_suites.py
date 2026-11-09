"""The conformance suites of `mcp_capability_router.testing`, run on the built-ins."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mcp_capability_router import (
    Capability,
    CapabilityRegistry,
    CapabilityRetriever,
    CapabilityType,
    InMemoryRegistry,
    InMemoryResultCacheStore,
    MCPAdapter,
    QdrantRetriever,
    ResultCacheStore,
)
from mcp_capability_router.testing import (
    CapabilityRegistryContract,
    CapabilityRetrieverContract,
    MCPAdapterContract,
    ResultCacheStoreContract,
    sample_capabilities,
)
from tests.support import FakeAdapter, mcp_prompt, mcp_resource, mcp_tool

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class MinimalRegistry(CapabilityRegistry):
    """Implements only the abstract methods, relying on the defaults for the rest."""

    def __init__(self) -> None:
        self.items: dict[str, Capability] = {}

    async def upsert_many(self, capabilities: Iterable[Capability]) -> None:
        self.items.update((c.capability_id, c) for c in capabilities)

    async def remove(self, capability_id: str) -> None:
        self.items.pop(capability_id, None)

    async def remove_server(self, server_id: str) -> None:
        self.items = {k: c for k, c in self.items.items() if c.server_id != server_id}

    async def get(self, capability_id: str) -> Capability | None:
        return self.items.get(capability_id)

    async def list(
        self, *, server_id: str | None = None, type: CapabilityType | None = None
    ) -> list[Capability]:
        return [
            c
            for c in self.items.values()
            if (server_id is None or c.server_id == server_id) and (type is None or c.type == type)
        ]


class TestInMemoryRegistry(CapabilityRegistryContract):
    async def make_registry(self) -> CapabilityRegistry:
        return InMemoryRegistry()


class TestMinimalRegistry(CapabilityRegistryContract):
    async def make_registry(self) -> CapabilityRegistry:
        return MinimalRegistry()


class TestQdrantRetriever(CapabilityRetrieverContract):
    async def make_retriever(self) -> CapabilityRetriever:
        return QdrantRetriever()


class TestInMemoryResultCacheStore(ResultCacheStoreContract):
    async def make_store(self) -> ResultCacheStore:
        return InMemoryResultCacheStore()


class TestAdapter(MCPAdapterContract):
    async def make_adapter(self) -> MCPAdapter:
        return FakeAdapter(
            tools=[mcp_tool("search")],
            resources=[mcp_resource("docs://handbook", "handbook")],
            prompts=[mcp_prompt("triage")],
        )


def test_adapter_contract_rejects_non_adapters() -> None:
    class Invalid(MCPAdapterContract):
        async def make_adapter(self) -> MCPAdapter:
            return object()  # type: ignore[return-value]

    with pytest.raises(AssertionError, match="does not subclass"):
        Invalid().test_connect_close_and_reconnect()
    with pytest.raises(AssertionError, match="does not subclass"):
        Invalid().test_listings_use_mcp_types_and_unique_identifiers()


class ForgetfulRegistry(MinimalRegistry):
    async def get(self, capability_id: str) -> Capability | None:
        return None


class Duplicating(CapabilityRetriever):
    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        return [candidates[0], candidates[0]]


def test_broken_implementations_fail_with_a_description() -> None:
    class Forgetful(CapabilityRegistryContract):
        async def make_registry(self) -> CapabilityRegistry:
            return ForgetfulRegistry()

    class NotARegistry(CapabilityRegistryContract):
        async def make_registry(self) -> CapabilityRegistry:
            return object()  # type: ignore[return-value]

    class Duplicates(CapabilityRetrieverContract):
        async def make_retriever(self) -> CapabilityRetriever:
            return Duplicating()

    with pytest.raises(AssertionError):
        Forgetful().test_round_trips_every_capability_type()
    with pytest.raises(AssertionError, match="does not subclass CapabilityRegistry"):
        NotARegistry().test_get_of_unknown_id_returns_none()
    with pytest.raises(AssertionError, match=r"duplicates|results for limit"):
        Duplicates().test_returns_only_candidates_within_the_limit()


def test_sample_capabilities_cover_every_type() -> None:
    samples = sample_capabilities("svc")
    assert sorted(str(c.type) for c in samples) == ["prompt", "resource", "tool"]
    assert all(c.capability_id.startswith("svc:") for c in samples)
