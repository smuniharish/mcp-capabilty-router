"""Keep the capability index in a Qdrant server, shared by every process.

By default `QdrantRetriever` keeps its collection in process. Give it an
`AsyncQdrantClient` and the collection lives in a Qdrant server instead: every
process of a service ranks against the same index, and capabilities that the
collection already holds are not embedded again, even after a restart.

Two runtimes stand in for two processes. With an embedding model, the second
runtime embeds nothing, because the first one indexed every capability.

Requires a Qdrant server:

    MCP_ROUTER_EXAMPLE_QDRANT_URL=http://localhost:6333

Set MCP_ROUTER_EXAMPLE_EMBEDDINGS as in 08_semantic_retrieval.py to rank by
meaning as well; without it, the collection ranks with BM25 only.
"""

import asyncio
import os
from collections.abc import Sequence

from common import billing_server, crm_server, docs_server
from qdrant_client import AsyncQdrantClient

from mcp_capability_router import Embedder, MCPRuntime, QdrantRetriever, RefreshPolicy

COLLECTION = "mcp_router_example"


class CountingEmbedder(Embedder):
    """Counts the texts that an embedder embeds."""

    def __init__(self, embedder: Embedder) -> None:
        self.embedder = embedder
        self.embedded = 0

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.embedded += len(texts)
        return await self.embedder.embed_documents(texts)

    async def embed_query(self, text: str) -> Sequence[float]:
        return await self.embedder.embed_query(text)


def load_embedder() -> Embedder | None:
    model = os.environ.get("MCP_ROUTER_EXAMPLE_EMBEDDINGS")
    if not model:
        return None
    from langchain.embeddings import init_embeddings

    from mcp_capability_router.integrations.langchain import LangChainEmbedder

    return LangChainEmbedder(init_embeddings(model))


async def process(name: str, client: AsyncQdrantClient, embedder: Embedder | None) -> None:
    counting = CountingEmbedder(embedder) if embedder is not None else None
    retriever = QdrantRetriever(embedder=counting, client=client, collection_name=COLLECTION)
    async with MCPRuntime(retriever=retriever) as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)
        [match] = await runtime.retrieve("refund an invoice", limit=1)
        print(f"{name}: best match {match.capability_id}")
        if counting is not None:
            print(f"{name}: embedded {counting.embedded} capability texts")


async def main(url: str, embedder: Embedder | None) -> None:
    client = AsyncQdrantClient(url=url)
    try:
        await client.delete_collection(COLLECTION)
        await process("first", client, embedder)
        points = await client.count(COLLECTION)
        print(f"points in the shared collection: {points.count}")
        await process("second", client, embedder)
    finally:
        await client.delete_collection(COLLECTION)
        await client.close()


if __name__ == "__main__":
    asyncio.run(main(os.environ["MCP_ROUTER_EXAMPLE_QDRANT_URL"], load_embedder()))
