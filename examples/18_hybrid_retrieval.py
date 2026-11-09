"""Combine exact-name retrieval with semantic retrieval using weighted rank fusion.

Set MCP_ROUTER_EXAMPLE_EMBEDDINGS as in 08_semantic_retrieval.py to use an embedding
service. Without it, deterministic test embeddings verify the wiring locally;
their rankings do not represent semantic quality.
"""

import asyncio
import os

from common import billing_server, crm_server, docs_server
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.vectorstores import InMemoryVectorStore

from mcp_capability_router import (
    EmbeddingRetriever,
    HybridRetriever,
    KeywordRetriever,
    MCPRuntime,
    RefreshPolicy,
)


async def main(embeddings: Embeddings) -> None:
    store = InMemoryVectorStore(embeddings)
    retriever = HybridRetriever(
        [KeywordRetriever(), EmbeddingRetriever(vector_store=store)],
        weights=[2, 1],
    )
    async with MCPRuntime(retriever=retriever) as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)
        for request in ("search_customers", "refund an invoice", "setup instructions"):
            matches = await runtime.retrieve(request, limit=2)
            print(f"{request!r}: {[match.capability_id for match in matches]}")


if __name__ == "__main__":
    model = os.environ.get("MCP_ROUTER_EXAMPLE_EMBEDDINGS")
    asyncio.run(main(init_embeddings(model) if model else DeterministicFakeEmbedding(size=128)))
