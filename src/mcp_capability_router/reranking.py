"""Optional abstract base class for a pluggable second-stage capability reranker.

Two-stage retrieval is a common pattern: a fast first-stage retriever (deterministic term
matching, a vector index, ...) narrows a large candidate set down to a manageable number,
then a slower, more precise reranker (typically a cross-encoder model) re-scores and
reorders that smaller set against the query. :class:`CapabilityReranker` models that
second stage as its own pluggable protocol, independent of which :class:`CapabilityRetriever`
produced the first-stage candidates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from .models import Capability
from .retrieval import CapabilityRetriever, CapabilityRetrieverBase


class CapabilityReranker(ABC):
    """Re-scores and reorders an already-retrieved candidate set against a query.

    Subclass this and implement :meth:`rerank`. A reranker never sees the full registry --
    only the (typically small) candidate set a first-stage retriever already selected --
    which keeps expensive models such as cross-encoders usable even at 10k+ capability scale.
    """

    @abstractmethod
    async def rerank(
        self, query: str, candidates: Sequence[Capability], *, limit: int = 20
    ) -> list[Capability]:
        """Return up to ``limit`` capabilities from ``candidates``, reordered by relevance."""


class RerankingRetriever(CapabilityRetrieverBase):
    """A :class:`CapabilityRetriever` that composes a first-stage retriever with a reranker.

    This is itself a plain ``CapabilityRetriever``, so it plugs into
    ``MCPRuntime(retriever=RerankingRetriever(...))`` with zero core changes -- the runtime
    never needs to know reranking is involved. The first-stage retriever is asked for
    ``overfetch_limit`` candidates (wider than the final ``limit``, so the reranker has a
    real pool to re-score), and the reranker narrows that down to ``limit``.
    """

    def __init__(
        self,
        first_stage: CapabilityRetriever,
        reranker: CapabilityReranker,
        *,
        overfetch_limit: int = 50,
    ) -> None:
        self._first_stage = first_stage
        self._reranker = reranker
        self._overfetch_limit = overfetch_limit

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int = 20
    ) -> list[Capability]:
        overfetch = max(limit, self._overfetch_limit)
        first_stage_results = await self._first_stage.retrieve(query, candidates, limit=overfetch)
        if not first_stage_results:
            return []
        return await self._reranker.rerank(query, first_stage_results, limit=limit)
