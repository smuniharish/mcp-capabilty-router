"""Rank capabilities by meaning as well as by words.

`LoomRetriever` ranks with BM25 by default. Give it an embedder and it ranks by
meaning too, fusing both rankings, so requests that share no words with a tool
still find it. Give it a reranker as well and a cross-encoder rescores the best
matches. `LangChainEmbedder` wraps any LangChain embedding model; subclass
`Embedder` to use any other embedding service, and retrievalloom's `RerankerABC`
to use any reranking model.

Requires an embedding model and, optionally, a reranking model, named as
described in retrieval_models.py:

    MCP_ROUTER_EXAMPLE_EMBEDDINGS=sentence-transformers:models/bge-m3
    MCP_ROUTER_EXAMPLE_RERANKER=models/bge-reranker-v2-m3
"""

import asyncio

from common import billing_server, crm_server, docs_server
from retrieval_models import load_embedder, load_reranker
from retrievalloom.contracts.models import RerankerABC

from mcp_capability_router import Embedder, LoomRetriever, MCPRuntime, RefreshPolicy

REQUESTS = (
    "give a customer their money back",
    "where are the setup instructions",
    "who is our contact at Acme",
)


async def main(embedder: Embedder, reranker: RerankerABC | None = None) -> None:
    retriever = LoomRetriever(embedder=embedder, reranker=reranker)
    async with MCPRuntime(retriever=retriever) as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)
        for request in REQUESTS:
            matches = await runtime.retrieve(request, limit=2)
            print(f"{request!r}: {[match.capability_id for match in matches]}")


if __name__ == "__main__":
    embedder = load_embedder()
    if embedder is None:
        raise SystemExit("set MCP_ROUTER_EXAMPLE_EMBEDDINGS to run this example")
    asyncio.run(main(embedder, load_reranker()))
