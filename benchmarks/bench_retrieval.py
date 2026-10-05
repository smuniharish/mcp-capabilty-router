"""Measure retrieval latency of the keyword and embedding retrievers.

Usage:
    python benchmarks/bench_retrieval.py
"""

from __future__ import annotations

import asyncio
import hashlib
import statistics
import time

from langchain_core.embeddings import Embeddings

from mcp_capability_router import (
    CapabilityRetriever,
    EmbeddingRetriever,
    KeywordRetriever,
    Tool,
)

VERBS = ("read", "write", "search", "list", "delete", "create", "update", "send")
NOUNS = ("file", "issue", "invoice", "email", "page", "record", "branch", "image")
QUERIES = ("search issues", "send an email", "read a file", "update the invoice")


class HashEmbeddings(Embeddings):
    """A fast, deterministic stand-in for an embedding model."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
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


async def measure(
    retriever: CapabilityRetriever, candidates: list[Tool], rounds: int
) -> float:
    await retriever.retrieve(QUERIES[0], candidates, limit=10)
    samples = []
    for round_number in range(rounds):
        query = QUERIES[round_number % len(QUERIES)]
        started = time.perf_counter()
        await retriever.retrieve(query, candidates, limit=10)
        samples.append(time.perf_counter() - started)
    return statistics.median(samples) * 1000


async def main() -> None:
    print(f"{'retriever':<10} {'capabilities':>12} {'median ms':>10}")
    for size in (100, 1_000, 10_000, 100_000):
        keyword = await measure(KeywordRetriever(), catalog(size), rounds=20)
        print(f"{'keyword':<10} {size:>12,} {keyword:>10.2f}")
    for size in (100, 1_000, 10_000):
        retriever = EmbeddingRetriever(HashEmbeddings())
        embedding = await measure(retriever, catalog(size), rounds=20)
        print(f"{'embedding':<10} {size:>12,} {embedding:>10.2f}")


if __name__ == "__main__":
    asyncio.run(main())
