"""Pluggable two-stage retrieval: a first-stage retriever composed with a reranker.

This demonstrates the ``CapabilityReranker`` protocol and the ``RerankingRetriever`` helper
(both in ``mcp_capability_router.reranking``), which model a common production retrieval
pattern: a cheap first-stage retriever narrows a (possibly large) candidate set down to a
manageable pool, then a more precise second-stage reranker re-scores and reorders that
pool against the query. ``RerankingRetriever`` is itself a plain ``CapabilityRetriever``, so
it plugs into ``MCPRuntime(retriever=...)`` exactly like ``DeterministicRetriever`` or
``QdrantCapabilityRetriever`` -- the runtime never needs to know two stages are involved.

Reranker implementation: a real BM25 (Okapi) lexical reranker (``rank-bm25``), not a
placeholder. BM25 is a genuine, widely used lexical ranking algorithm (the same family used
by Elasticsearch/OpenSearch's default relevance scoring), and is used here deliberately
instead of a neural cross-encoder: this project's development sandbox has an explicit,
non-negotiable corporate content-policy block on Hugging Face's model-download endpoints
(``huggingface.co/.../resolve/...`` returns HTTP 403 with a literal "Noncompliant action"
block page, confirmed for both ``sentence-transformers`` cross-encoders and ``fastembed``'s
mirrored copies) -- the same class of block documented for ``registry.ollama.ai`` in
``examples/embedding_ollama.py``. Rather than claim a neural reranker was "tested" when it
could not actually be downloaded and run in this environment, this example demonstrates the
identical ``CapabilityReranker`` extension point with a reranking algorithm that needs no
model download at all, and is 100% real, run, and verified here. A neural cross-encoder
(``sentence-transformers.CrossEncoder``, a hosted reranking API, etc.) is a drop-in
alternative ``CapabilityReranker`` implementation in an unrestricted environment; only the
``rerank()`` method body would change.

Run:

    uv sync --extra examples   # installs rank-bm25
    uv run python -m examples.reranking_bm25

No external service, network access, or credentials are required.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from rank_bm25 import BM25Okapi

from mcp_capability_router import (
    CapabilityReranker,
    CapabilityType,
    DeterministicRetriever,
    MCPRuntime,
    RerankingRetriever,
)
from mcp_capability_router.models import Capability


class SupportDeskAdapter:
    """A slightly larger in-process adapter (5 tools) so BM25 has enough of a corpus for
    its IDF weighting to meaningfully differentiate candidates -- with only 1-2 near-identical
    length documents, BM25's IDF term collapses toward zero for any term shared by most of
    the corpus, which is expected, real BM25 behavior on a toy-sized document set, not a bug.
    """

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [
            {"name": "search_orders", "description": "search customer orders by status"},
            {"name": "issue_refund", "description": "issue a refund for a completed order"},
            {"name": "cancel_subscription", "description": "cancel a customer subscription"},
            {"name": "update_shipping_address", "description": "update an order shipping address"},
            {"name": "escalate_to_manager", "description": "escalate a ticket to a manager"},
        ]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


class BM25Reranker(CapabilityReranker):
    """A real ``CapabilityReranker`` backed by the BM25 Okapi lexical ranking algorithm.

    Each ``rerank`` call builds a fresh BM25 index over just the (small) candidate set it
    receives -- this is deliberately cheap and stateless, since the whole point of a
    second-stage reranker is that it only ever runs against a first stage's narrowed-down
    pool, never the full registry.
    """

    async def rerank(
        self, query: str, candidates: Sequence[Capability], *, limit: int = 20
    ) -> list[Capability]:
        if not candidates:
            return []
        corpus = [f"{c.name} {c.description or ''}".lower().split() for c in candidates]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(query.lower().split())
        ranked = sorted(
            zip(scores, candidates, strict=True), key=lambda pair: pair[0], reverse=True
        )
        return [capability for _, capability in ranked[:limit]]


async def main() -> None:
    retriever = RerankingRetriever(
        first_stage=DeterministicRetriever(),
        reranker=BM25Reranker(),
        overfetch_limit=10,
    )

    async with MCPRuntime(retriever=retriever) as runtime:
        await runtime.register_server("commerce", lambda: SupportDeskAdapter())
        await runtime.refresh_server("commerce")

        tools = await runtime.retrieve("refund a customer order", type=CapabilityType.TOOL)
        print("first-stage + BM25-reranked tools:", [tool.name for tool in tools])

        result = await runtime.execute(tools[0].capability_id, {"order_id": "ord_123"})
        print("executed:", result)


if __name__ == "__main__":
    asyncio.run(main())
