"""Measure how fast `LoomRetriever` starts, indexes a catalog, and answers queries.

Reports the engine's cold start, the first query over the catalog, which indexes
it, and the median of the queries that follow. The lexical mode ranks with BM25
only; the hybrid mode adds a fast deterministic stand-in for an embedding model,
so its numbers measure the retriever, not a model. Set
`MCP_ROUTER_EXAMPLE_EMBEDDINGS`, as for the examples, to add a mode with a real
embedding model on smaller catalogs.

Usage:
    python benchmarks/bench_retrieval.py
    MCP_ROUTER_EXAMPLE_EMBEDDINGS=sentence-transformers:models/bge-m3 \
        python benchmarks/bench_retrieval.py
"""

from __future__ import annotations

import asyncio
import hashlib
import statistics
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from mcp_capability_router import Embedder, LoomRetriever, Tool

if TYPE_CHECKING:
    from collections.abc import Sequence

VERBS = ("read", "write", "search", "list", "delete", "create", "update", "send")
NOUNS = ("file", "issue", "invoice", "email", "page", "record", "branch", "image")
QUERIES = ("search issues", "send an email", "read a file", "update the invoice")
SIZES = (100, 1_000, 10_000)
MODEL_SIZES = (100, 1_000)
ROUNDS = 20


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


def model_embedder() -> Embedder | None:
    """Load the examples' embedding model, if one is configured."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "examples"))
    from retrieval_models import load_embedder

    return load_embedder()


async def run(embedder: Embedder | None, size: int) -> tuple[float, float, float]:
    candidates = catalog(size)
    retriever = LoomRetriever(embedder=embedder, max_documents=size)
    try:
        started = time.perf_counter()
        await retriever.retrieve(QUERIES[0], candidates[:1], limit=10)
        startup = time.perf_counter() - started
        started = time.perf_counter()
        await retriever.retrieve(QUERIES[0], candidates, limit=10)
        indexing = time.perf_counter() - started
        samples = []
        for round_number in range(ROUNDS):
            query = QUERIES[round_number % len(QUERIES)]
            started = time.perf_counter()
            await retriever.retrieve(query, candidates, limit=10)
            samples.append(time.perf_counter() - started)
    finally:
        await retriever.close()
    return startup * 1000, indexing * 1000, statistics.median(samples) * 1000


async def main() -> None:
    modes: list[tuple[str, Embedder | None, tuple[int, ...]]] = [
        ("lexical", None, SIZES),
        ("hybrid", HashEmbedder(), SIZES),
    ]
    if (embedder := model_embedder()) is not None:
        modes.append(("model", embedder, MODEL_SIZES))
    print(
        f"{'mode':<8} {'capabilities':>12} {'start ms':>9} {'first query ms':>15} {'median ms':>10}"
    )
    for mode, mode_embedder, sizes in modes:
        for size in sizes:
            startup, indexing, query = await run(mode_embedder, size)
            print(f"{mode:<8} {size:>12,} {startup:>9.0f} {indexing:>15.1f} {query:>10.2f}")


if __name__ == "__main__":
    asyncio.run(main())
