from __future__ import annotations

import re
from collections.abc import Sequence

import pytest
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.embeddings import Embeddings
from pydantic import Field

from mcp_capability_router import (
    CapabilityRetriever,
    ConfigurationError,
    EmbeddingRetriever,
    Tool,
)
from tests.support import capability_ids, resource, tool

VOCABULARY = ("read", "file", "send", "email", "weather", "forecast", "notes")


class WordEmbeddings(Embeddings):
    """Embeds texts as bags of known words, so similarity is word overlap."""

    def __init__(self) -> None:
        self.documents: list[str] = []
        self.queries: list[str] = []

    @staticmethod
    def _vector(text: str) -> list[float]:
        words = set(re.findall(r"[a-z]+", text.lower()))
        return [1.0 if word in words else 0.0 for word in VOCABULARY] + [0.01]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self._vector(text)


class ReverseReranker(BaseDocumentCompressor):
    """Reverses the order of the documents it receives."""

    received: list[int] = Field(default_factory=list)

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> Sequence[Document]:
        self.received.append(len(documents))
        return list(reversed(documents))


def catalog() -> list[Tool]:
    return [
        tool("s", "read_file", "Read a file"),
        tool("s", "send_email", "Send an email"),
        tool("s", "forecast", "Weather forecast"),
    ]


async def test_retriever_implements_the_contract() -> None:
    assert isinstance(EmbeddingRetriever(WordEmbeddings()), CapabilityRetriever)


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_settings_are_rejected(value: object) -> None:
    with pytest.raises(ConfigurationError, match="fetch_k"):
        EmbeddingRetriever(WordEmbeddings(), fetch_k=value)  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="max_documents"):
        EmbeddingRetriever(WordEmbeddings(), max_documents=value)  # type: ignore[arg-type]


async def test_ranks_candidates_by_similarity() -> None:
    retriever = EmbeddingRetriever(WordEmbeddings())
    ranked = await retriever.retrieve("read a file", catalog(), limit=2)
    assert capability_ids(ranked)[0] == "s:tool:read_file"
    assert len(ranked) == 2
    with pytest.raises(ConfigurationError):
        await retriever.retrieve("x", catalog(), limit=0)


async def test_empty_candidates_embed_nothing() -> None:
    embeddings = WordEmbeddings()
    assert await EmbeddingRetriever(embeddings).retrieve("x", [], limit=3) == []
    assert embeddings.queries == []


async def test_only_current_candidates_are_returned() -> None:
    retriever = EmbeddingRetriever(WordEmbeddings())
    await retriever.retrieve("email", catalog(), limit=3)
    notes = [resource("s", "resource://notes", "notes", tags=frozenset({"read"}))]
    assert capability_ids(await retriever.retrieve("email", notes, limit=3)) == [
        "s:resource:resource://notes"
    ]
    assert retriever._texts["s:resource:resource://notes"] == (
        "notes (resource: notes)\nTags: read\nURI: resource://notes"
    )


async def test_capabilities_are_embedded_once_until_they_change() -> None:
    embeddings = WordEmbeddings()
    retriever = EmbeddingRetriever(embeddings)
    await retriever.retrieve("weather", catalog(), limit=1)
    await retriever.retrieve("email", catalog(), limit=1)
    assert len(embeddings.documents) == 3
    changed = [*catalog()[:2], tool("s", "forecast", "Weather forecast for a city")]
    await retriever.retrieve("weather", changed, limit=1)
    assert len(embeddings.documents) == 4


async def test_reranker_reorders_the_fetched_matches() -> None:
    reranker = ReverseReranker()
    retriever = EmbeddingRetriever(WordEmbeddings(), reranker=reranker, fetch_k=3)
    ranked = await retriever.retrieve("read a file", catalog(), limit=1)
    assert reranker.received[-1] == 3
    assert capability_ids(ranked) != ["s:tool:read_file"]


async def test_least_recently_seen_vectors_are_evicted() -> None:
    embeddings = WordEmbeddings()
    retriever = EmbeddingRetriever(embeddings, max_documents=2)
    first, second, third = catalog()
    await retriever.retrieve("x", [first, second], limit=2)
    await retriever.retrieve("x", [third], limit=1)
    assert set(retriever._texts) == {second.capability_id, third.capability_id}
    await retriever.retrieve("read", [first], limit=1)
    assert len(embeddings.documents) == 4

    crowded = EmbeddingRetriever(WordEmbeddings(), max_documents=1)
    assert len(await crowded.retrieve("x", catalog(), limit=3)) == 3
    assert len(crowded._texts) == 3


async def test_failed_embedding_calls_leave_the_retriever_consistent() -> None:
    class FlakyEmbeddings(WordEmbeddings):
        def __init__(self) -> None:
            super().__init__()
            self.failures = 1

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            if self.failures:
                self.failures -= 1
                msg = "rate limited"
                raise ConnectionError(msg)
            return super().embed_documents(texts)

    retriever = EmbeddingRetriever(FlakyEmbeddings(), max_documents=1)
    first, second, third = catalog()
    with pytest.raises(ConnectionError, match="rate limited"):
        await retriever.retrieve("read", [first], limit=1)
    assert retriever._seen == {}
    for _ in range(2):
        ranked = await retriever.retrieve("email", [second, third], limit=1)
        assert capability_ids(ranked) == ["s:tool:send_email"]
    assert set(retriever._texts) == set(retriever._seen)
    ranked = await retriever.retrieve("read", [first], limit=1)
    assert capability_ids(ranked) == ["s:tool:read_file"]
