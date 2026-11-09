"""Hybrid retrieval and embedding retrieval over a persistent vector store."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore

from mcp_capability_router import (
    Capability,
    CapabilityRetriever,
    ConfigurationError,
    EmbeddingRetriever,
    HybridRetriever,
    KeywordRetriever,
)
from tests.support import capability_ids, tool
from tests.unit.test_embedding_retrieval import WordEmbeddings, catalog

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from langchain_core.embeddings import Embeddings


class Fixed(CapabilityRetriever):
    """Returns the candidates in a fixed order of names."""

    def __init__(self, *names: str) -> None:
        self.names = names

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        by_name = {capability.name: capability for capability in candidates}
        return [by_name[name] for name in self.names if name in by_name][:limit]


CANDIDATES = [tool("s", name) for name in ("a", "b", "c", "d")]


class TestHybridRetriever:
    async def test_fuses_rankings_by_reciprocal_rank(self) -> None:
        hybrid = HybridRetriever([Fixed("a", "b", "c"), Fixed("c", "b", "a")])
        # 1/61 + 1/63 beats 2/62: one first place outweighs two second places.
        assert capability_ids(await hybrid.retrieve("q", CANDIDATES, limit=4)) == [
            "s:tool:a",
            "s:tool:c",
            "s:tool:b",
        ]
        weighted = HybridRetriever(
            [Fixed("a", "b", "c"), Fixed("c", "b", "a")], weights=[1, 3], k=1
        )
        assert capability_ids(await weighted.retrieve("q", CANDIDATES, limit=1)) == ["s:tool:c"]
        assert await hybrid.retrieve("q", [], limit=3) == []
        assert len(hybrid.retrievers) == 2

    async def test_combines_keywords_and_embeddings(self) -> None:
        hybrid = HybridRetriever(
            [KeywordRetriever(), EmbeddingRetriever(WordEmbeddings())], fetch_k=5
        )
        assert (await hybrid.retrieve("send email", catalog(), limit=1))[0].name == ("send_email")

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ({"retrievers": []}, "at least one"),
            ({"retrievers": [object()]}, "does not subclass"),
            ({"retrievers": [Fixed()], "weights": [1, 2]}, "2 weights for 1"),
            ({"retrievers": [Fixed()], "weights": [-1]}, "non-negative"),
            ({"retrievers": [Fixed()], "weights": [float("inf")]}, "finite"),
            ({"retrievers": [Fixed()], "k": 0}, "k"),
            ({"retrievers": [Fixed()], "fetch_k": 0}, "fetch_k"),
        ],
    )
    def test_rejects_invalid_arguments(self, arguments: dict[str, Any], message: str) -> None:
        with pytest.raises(ConfigurationError, match=message):
            HybridRetriever(**arguments)

    async def test_validates_the_limit(self) -> None:
        with pytest.raises(ConfigurationError, match="limit"):
            await HybridRetriever([Fixed()]).retrieve("q", CANDIDATES, limit=0)


class ExternalStore(VectorStore):
    """A vector store that is not an `InMemoryVectorStore`, backed by one."""

    def __init__(self, embeddings: Embeddings, *, lookups: bool = True) -> None:
        self.inner = InMemoryVectorStore(embeddings)
        self.lookups = lookups
        self.searches: list[int] = []

    @property
    def embeddings(self) -> Embeddings:
        return self.inner.embeddings

    @classmethod
    def from_texts(cls, *args: Any, **kwargs: Any) -> ExternalStore:
        raise NotImplementedError

    def similarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        raise NotImplementedError

    async def aadd_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        return await self.inner.aadd_documents(documents, **kwargs)

    async def adelete(self, ids: list[str] | None = None, **kwargs: Any) -> bool | None:
        return await self.inner.adelete(ids)

    async def asimilarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        self.searches.append(k)
        return await self.inner.asimilarity_search(query, k=k)

    async def aget_by_ids(self, ids: Iterable[str], /) -> list[Document]:
        if not self.lookups:
            raise NotImplementedError
        # Some stores return more than was asked for; the extras must be ignored.
        return [*await self.inner.aget_by_ids(list(ids)), Document(id="x", page_content="")]


class TestPersistentVectorStores:
    async def test_needs_embeddings_or_a_store(self) -> None:
        with pytest.raises(ConfigurationError, match="embeddings or a vector_store"):
            EmbeddingRetriever()
        with pytest.raises(ConfigurationError, match="VectorStore"):
            EmbeddingRetriever(vector_store=object())  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError, match="Embeddings"):
            EmbeddingRetriever(object())  # type: ignore[arg-type]
        store = ExternalStore(WordEmbeddings())
        assert EmbeddingRetriever(vector_store=store).vector_store is store

    async def test_a_restarted_retriever_reuses_stored_vectors(self) -> None:
        embeddings = WordEmbeddings()
        store = ExternalStore(embeddings)
        first = EmbeddingRetriever(vector_store=store)
        assert (await first.retrieve("send email", catalog(), limit=1))[0].name == "send_email"
        embedded = len(embeddings.documents)
        second = EmbeddingRetriever(vector_store=store)
        assert (await second.retrieve("read file", catalog(), limit=1))[0].name == "read_file"
        assert len(embeddings.documents) == embedded

    async def test_stores_without_lookups_re_embed(self) -> None:
        embeddings = WordEmbeddings()
        store = ExternalStore(embeddings, lookups=False)
        await EmbeddingRetriever(vector_store=store).retrieve("notes", catalog(), limit=1)
        embedded = len(embeddings.documents)
        await EmbeddingRetriever(vector_store=store).retrieve("notes", catalog(), limit=1)
        assert len(embeddings.documents) == 2 * embedded

    async def test_searches_widen_until_enough_candidates_match(self) -> None:
        store = ExternalStore(WordEmbeddings())
        retriever = EmbeddingRetriever(vector_store=store)
        others = [tool("other", f"weather_{index}", "weather forecast") for index in range(60)]
        await retriever.retrieve("weather", others, limit=1)
        wanted = catalog()
        store.searches.clear()
        found = await retriever.retrieve("weather forecast", wanted, limit=2)
        assert {capability.server_id for capability in found} <= {"s"}
        assert len(found) == 2
        assert len(store.searches) > 1
