from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Protocol

from .models import Capability
from .routing import filter_capabilities, rank_capabilities


class CapabilityRetriever(Protocol):
    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int = 20
    ) -> list[Capability]: ...


class CapabilityRetrieverBase(ABC):
    """Optional abstract base class for a custom :class:`CapabilityRetriever`.

    As with :class:`~mcp_capability_router.registry.CapabilityRegistryBase`, ``MCPRuntime``
    only requires the structural ``retrieve(...)`` shape; subclassing here is a convenience
    for implementers who want an explicit, enforced contract (for example a vector-backed
    retriever such as ``QdrantCapabilityRetriever`` in the examples).
    """

    @abstractmethod
    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int = 20
    ) -> list[Capability]:
        """Return up to ``limit`` capabilities from ``candidates`` ranked against ``query``."""


class DeterministicRetriever:
    """Small default retriever that applications can replace with lexical or vector search."""

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int = 20
    ) -> list[Capability]:
        return rank_capabilities(filter_capabilities(candidates), query)[:limit]
