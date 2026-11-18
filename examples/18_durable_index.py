"""Keep the capability index across restarts, with vectors in a Qdrant server.

By default `LoomRetriever` keeps its index in memory, so a restarted process
embeds every capability again. Give it a data directory and RetrievalLoom keeps
its records there, in SQLite, and the vectors in local Qdrant files: after a
restart, only the capabilities that changed are embedded. Give it a
`QdrantVectorStore` as well and the vectors live in a Qdrant server instead.

Two runtimes, one after the other, stand in for a process and its restart.

Requires an embedding model, named as described in retrieval_models.py, and
optionally a Qdrant server:

    MCP_ROUTER_EXAMPLE_EMBEDDINGS=sentence-transformers:models/bge-m3
    MCP_ROUTER_EXAMPLE_QDRANT_URL=http://localhost:6333
"""

import asyncio
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from common import billing_server, crm_server, docs_server
from qdrant_client import AsyncQdrantClient
from retrieval_models import load_embedder
from retrievalloom import Components, EngineResources
from retrievalloom.index.vector import QdrantVectorStore

from mcp_capability_router import Embedder, LoomRetriever, MCPRuntime, RefreshPolicy

COLLECTIONS = "mcp_router_example"


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


async def process(
    name: str, data_dir: Path, embedder: Embedder, client: AsyncQdrantClient | None
) -> None:
    counting = CountingEmbedder(embedder)
    store = (
        None if client is None else QdrantVectorStore(client=client, collection_prefix=COLLECTIONS)
    )
    retriever = LoomRetriever(
        embedder=counting,
        components=None if store is None else Components(vector_store=store),
        resources=EngineResources(data_dir=data_dir),
    )
    try:
        async with MCPRuntime(retriever=retriever) as runtime:
            policy = RefreshPolicy(on_register=True)
            await runtime.register_mcp("crm", crm_server(), refresh=policy)
            await runtime.register_mcp("billing", billing_server(), refresh=policy)
            await runtime.register_mcp("docs", docs_server(), refresh=policy)
            [match] = await runtime.retrieve("refund an invoice", limit=1)
            print(f"{name}: best match {match.capability_id}")
            print(f"{name}: embedded {counting.embedded} capability texts")
    finally:
        # The engine leaves components that it was given open.
        if store is not None:
            await store.close()


async def main(data_dir: Path, embedder: Embedder, qdrant_url: str | None = None) -> None:
    client = None if qdrant_url is None else AsyncQdrantClient(url=qdrant_url)
    try:
        await process("first", data_dir, embedder, client)
        await process("restarted", data_dir, embedder, client)
    finally:
        if client is not None:
            for collection in (await client.get_collections()).collections:
                if collection.name.startswith(COLLECTIONS):
                    await client.delete_collection(collection.name)
            await client.close()


if __name__ == "__main__":
    embedder = load_embedder()
    if embedder is None:
        raise SystemExit("set MCP_ROUTER_EXAMPLE_EMBEDDINGS to run this example")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        url = os.environ.get("MCP_ROUTER_EXAMPLE_QDRANT_URL") or None
        asyncio.run(main(Path(directory), embedder, url))
