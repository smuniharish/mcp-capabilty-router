"""Measure how fast `QdrantRetriever` indexes a catalog and answers queries.

Times the first query, which indexes the whole catalog, and the median of the
queries that follow, in the sparse (BM25) and hybrid modes. The hybrid mode uses
a fast deterministic stand-in for an embedding model, so the numbers measure the
retriever and Qdrant, not the model.

Usage:
    python benchmarks/bench_retrieval.py
    MCP_ROUTER_BENCH_QDRANT_URL=http://localhost:6333 python benchmarks/bench_retrieval.py
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import statistics
import time
from typing import TYPE_CHECKING

from qdrant_client import AsyncQdrantClient

from mcp_capability_router import Embedder, QdrantRetriever, Tool

if TYPE_CHECKING:
    from collections.abc import Sequence

VERBS = ("read", "write", "search", "list", "delete", "create", "update", "send")
NOUNS = ("file", "issue", "invoice", "email", "page", "record", "branch", "image")
QUERIES = ("search issues", "send an email", "read a file", "update the invoice")
SIZES = (100, 1_000, 10_000)
ROUNDS = 20
COLLECTION = "mcp_router_bench"


class HashEmbedder(Embedder):
    """A fast, deterministic stand-in for an embedding model."""

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [await self.embed_query(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        return [byte / 255 for byte in digest]


def catalog(size: int) -> list[Tool]:
    tools = []
    for index in range(size):
        verb, noun = VERBS[index % 8], NOUNS[index // 8 % 8]
        name = f"{verb}_{noun}_{index}"
        tools.append(
            Tool(
                capability_id=f"s{index % 50}:tool:{name}",
                server_id=f"s{index % 50}",
                name=name,
                description=f"{verb.title()} a {noun} by its ID.",
            )
        )
    return tools


async def measure(retriever: QdrantRetriever, candidates: list[Tool]) -> tuple[float, float]:
    started = time.perf_counter()
    await retriever.retrieve(QUERIES[0], candidates, limit=10)
    indexing = time.perf_counter() - started
    samples = []
    for round_number in range(ROUNDS):
        query = QUERIES[round_number % len(QUERIES)]
        started = time.perf_counter()
        await retriever.retrieve(query, candidates, limit=10)
        samples.append(time.perf_counter() - started)
    return indexing * 1000, statistics.median(samples) * 1000


async def run(mode: str, size: int, url: str | None) -> tuple[float, float]:
    client = AsyncQdrantClient(url=url) if url else None
    if client is not None and await client.collection_exists(COLLECTION):
        await client.delete_collection(COLLECTION)
    embedder = HashEmbedder() if mode == "hybrid" else None
    retriever = QdrantRetriever(embedder=embedder, client=client, collection_name=COLLECTION)
    try:
        return await measure(retriever, catalog(size))
    finally:
        await retriever.close()
        if client is not None:
            await client.delete_collection(COLLECTION)
            await client.close()


async def main() -> None:
    url = os.environ.get("MCP_ROUTER_BENCH_QDRANT_URL")
    print(f"qdrant: {url or 'in-process'}")
    print(f"{'mode':<8} {'capabilities':>12} {'first query ms':>15} {'median ms':>10}")
    for mode in ("sparse", "hybrid"):
        for size in SIZES:
            indexing, query = await run(mode, size, url)
            print(f"{mode:<8} {size:>12,} {indexing:>15.1f} {query:>10.2f}")


if __name__ == "__main__":
    asyncio.run(main())
