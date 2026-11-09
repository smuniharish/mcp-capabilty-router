"""The default Qdrant retriever: sparse BM25, dense embeddings, and hybrid fusion."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
from qdrant_client import AsyncQdrantClient, models

from mcp_capability_router import (
    CapabilityRetriever,
    ConfigurationError,
    Embedder,
    QdrantRetriever,
    Tool,
    document_text,
)
from mcp_capability_router.retrieval import _point_id, _terms, _words
from tests.support import capability_ids, resource, tool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

VOCABULARY = ("read", "file", "send", "email", "weather", "forecast", "notes")


class WordEmbedder(Embedder):
    """Embeds texts as bags of known words, so similarity is word overlap."""

    def __init__(self, size: int | None = None) -> None:
        self.documents: list[str] = []
        self.queries: list[str] = []
        self.size = size
        self.failures = 0

    @staticmethod
    def vector(text: str) -> list[float]:
        words = set(re.findall(r"[a-z]+", text.lower()))
        return [1.0 if word in words else 0.0 for word in VOCABULARY] + [0.01]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.failures:
            self.failures -= 1
            msg = "rate limited"
            raise ConnectionError(msg)
        self.documents.extend(texts)
        return [self.vector(text)[: self.size] for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self.vector(text)[: self.size]


def catalog() -> list[Tool]:
    return [
        tool("s", "read_file", "Read a file"),
        tool("s", "send_email", "Send an email"),
        tool("s", "forecast", "Weather forecast"),
    ]


@pytest.fixture
async def client() -> AsyncIterator[AsyncQdrantClient]:
    instance = AsyncQdrantClient(":memory:")
    yield instance
    await instance.close()


class TestText:
    @pytest.mark.parametrize(
        ("text", "words"),
        [
            ("read_text_file", ["read", "text", "file"]),
            ("readTextFile", ["read", "text", "file"]),
            ("read-text-file", ["read", "text", "file"]),
            ("HTTPServer v2", ["http", "server", "v", "2"]),
            ("resource://notes/readme.md", ["resource", "notes", "readme", "md"]),
            ("Café menu", ["café", "menu"]),
            ("  ", []),
        ],
    )
    def test_words_split_identifiers_and_prose(self, text: str, words: list[str]) -> None:
        assert list(_words(text)) == words

    def test_terms_drop_stop_words_and_plurals_and_add_stems(self) -> None:
        assert list(_terms("the files of a class")) == [("file", 1.0), ("class", 1.0)]
        assert list(_terms("navigation")) == [("navigation", 1.0), ("~navig", 0.5)]
        assert list(_terms("bus")) == [("bus", 1.0)]

    def test_document_text(self) -> None:
        assert document_text(tool("s", "read_file", "Read a file")) == (
            "read file (tool: read_file)\nRead a file"
        )
        notes = resource("s", "resource://notes", "notes", tags=frozenset({"b", "a"}))
        assert document_text(notes) == "notes (resource: notes)\nTags: a, b\nURI: resource://notes"
        assert document_text(tool("s", "__", title="Odd")) == "Odd (tool: __)"
        assert document_text(tool("s", "__")) == "__ (tool: __)"


class TestConfiguration:
    def test_defaults(self) -> None:
        retriever = QdrantRetriever()
        assert isinstance(retriever, CapabilityRetriever)
        assert (retriever.mode, retriever.collection_name) == ("sparse", "mcp_capabilities")
        assert QdrantRetriever(embedder=WordEmbedder()).mode == "hybrid"
        assert QdrantRetriever(embedder=WordEmbedder(), mode="dense").mode == "dense"

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ({"embedder": object()}, "does not subclass Embedder"),
            ({"mode": "fuzzy"}, "mode must be"),
            ({"mode": "sparse", "embedder": WordEmbedder()}, "does not use an embedder"),
            ({"mode": "dense"}, "dense mode needs an embedder"),
            ({"mode": "hybrid"}, "hybrid mode needs an embedder"),
            ({"client": object()}, "is not a qdrant_client.AsyncQdrantClient"),
            ({"collection_name": ""}, "collection_name"),
            ({"fusion": "max"}, "fusion must be"),
            ({"rrf_k": 0}, "rrf_k"),
            ({"rrf_k": 10, "fusion": "dbsf"}, "only to the 'rrf' fusion"),
            ({"prefetch_limit": 0}, "prefetch_limit"),
            ({"max_points": True}, "max_points"),
            ({"k1": -1}, "k1"),
            ({"k1": float("nan")}, "k1"),
            ({"k1": True}, "k1"),
            ({"b": 1.5}, "b is out of range"),
            ({"avg_length": 0}, "avg_length"),
            ({"avg_length": "24"}, "avg_length"),
        ],
    )
    def test_rejects_invalid_arguments(self, arguments: dict[str, Any], message: str) -> None:
        with pytest.raises(ConfigurationError, match=message):
            QdrantRetriever(**arguments)

    async def test_validates_the_limit_and_skips_empty_candidates(self) -> None:
        retriever = QdrantRetriever()
        with pytest.raises(ConfigurationError, match="limit"):
            await retriever.retrieve("x", catalog(), limit=0)
        assert await retriever.retrieve("x", [], limit=3) == []


class TestSparse:
    @pytest.fixture
    async def retriever(self) -> AsyncIterator[QdrantRetriever]:
        instance = QdrantRetriever()
        yield instance
        await instance.close()

    async def test_matches_words_plurals_and_stems_but_not_substrings(
        self, retriever: QdrantRetriever
    ) -> None:
        candidates = [
            tool("s", "read_text_file", "Read a file from disk"),
            tool("s", "thread_dump", "Dump the threads of a process"),
            tool("s", "navigate", "Open a page in the browser"),
        ]

        async def ids(query: str) -> list[str]:
            return capability_ids(await retriever.retrieve(query, candidates, limit=5))

        assert await ids("read") == ["s:tool:read_text_file"]
        assert await ids("files") == ["s:tool:read_text_file"]
        assert await ids("threads") == ["s:tool:thread_dump"]
        assert await ids("navigation") == ["s:tool:navigate"]
        assert await ids("re") == []

    async def test_name_matches_outrank_tag_and_description_matches(
        self, retriever: QdrantRetriever
    ) -> None:
        candidates = [
            tool("s", "c_describes", "Search everything"),
            tool("s", "b_tagged", tags=frozenset({"search"})),
            tool("s", "a_search_named", "Find by name"),
        ]
        assert capability_ids(await retriever.retrieve("search", candidates, limit=3)) == [
            "s:tool:a_search_named",
            "s:tool:b_tagged",
            "s:tool:c_describes",
        ]

    async def test_rare_words_outweigh_common_words(self, retriever: QdrantRetriever) -> None:
        candidates = [tool("s", f"file_tool_{index}", "file utility") for index in range(9)]
        candidates.append(tool("s", "archive", "file archive utility"))
        ranked = await retriever.retrieve("archive file", candidates, limit=3)
        assert ranked[0].capability_id == "s:tool:archive"

    async def test_resource_uris_and_titles_are_searchable(
        self, retriever: QdrantRetriever
    ) -> None:
        candidates = [
            resource("s", "resource://notes/readme", "readme"),
            tool("s", "x1", title="Weather forecast"),
        ]
        assert capability_ids(await retriever.retrieve("notes", candidates, limit=2)) == [
            "s:resource:resource://notes/readme"
        ]
        assert capability_ids(await retriever.retrieve("weather", candidates, limit=2)) == [
            "s:tool:x1"
        ]

    async def test_queries_without_words_list_candidates_by_id(
        self, retriever: QdrantRetriever
    ) -> None:
        candidates = [tool("s", "b"), tool("s", "a"), tool("s", "c")]
        assert capability_ids(await retriever.retrieve("", candidates, limit=2)) == [
            "s:tool:a",
            "s:tool:b",
        ]
        assert capability_ids(await retriever.retrieve("the of", candidates, limit=5)) == [
            "s:tool:a",
            "s:tool:b",
            "s:tool:c",
        ]

    async def test_ties_are_broken_by_capability_id(self, retriever: QdrantRetriever) -> None:
        names = ["delta", "alpha", "echo", "charlie", "bravo"]
        candidates = [tool("s", name, "search records") for name in names]
        ranked = await retriever.retrieve("search", candidates, limit=2)
        assert capability_ids(ranked) == ["s:tool:alpha", "s:tool:bravo"]
        candidates.append(tool("s", "search", "search"))
        ranked = await retriever.retrieve("search", list(reversed(candidates)), limit=3)
        assert capability_ids(ranked) == ["s:tool:search", "s:tool:alpha", "s:tool:bravo"]

    async def test_only_the_given_candidates_are_returned(self, retriever: QdrantRetriever) -> None:
        await retriever.retrieve("email", catalog(), limit=3)
        ranked = await retriever.retrieve("email", catalog()[:1], limit=3)
        assert ranked == []
        ranked = await retriever.retrieve("email file", catalog()[:2], limit=3)
        assert sorted(capability_ids(ranked)) == ["s:tool:read_file", "s:tool:send_email"]

    async def test_changed_capabilities_are_reindexed(self, retriever: QdrantRetriever) -> None:
        assert capability_ids(await retriever.retrieve("old", [tool("s", "x", "old")], limit=1))
        digest = retriever._digests["s:tool:x"]
        await retriever.retrieve("old", [tool("s", "x", "old")], limit=1)
        assert retriever._digests["s:tool:x"] == digest
        changed = [tool("s", "x", "new")]
        assert capability_ids(await retriever.retrieve("new", changed, limit=1)) == ["s:tool:x"]
        assert await retriever.retrieve("old", changed, limit=1) == []

    async def test_least_recently_seen_points_are_evicted(self) -> None:
        retriever = QdrantRetriever(max_points=2)
        first, second, third = catalog()
        await retriever.retrieve("x", [first, second], limit=2)
        await retriever.retrieve("x", [third], limit=1)
        assert set(retriever._digests) == {second.capability_id, third.capability_id}
        count = await retriever.client.count(retriever.collection_name)
        assert count.count == 2
        crowded = QdrantRetriever(max_points=1)
        assert len(await crowded.retrieve("read email forecast", catalog(), limit=3)) == 3
        assert len(crowded._digests) == 3
        await retriever.close()
        await crowded.close()

    async def test_close_releases_an_owned_client(self) -> None:
        retriever = QdrantRetriever()
        await retriever.retrieve("email", catalog(), limit=1)
        first = retriever.client
        await retriever.close()
        await retriever.close()
        assert retriever._digests == {}
        assert capability_ids(await retriever.retrieve("email", catalog(), limit=1)) == [
            "s:tool:send_email"
        ]
        assert retriever.client is not first
        await retriever.close()


class TestDense:
    async def test_ranks_by_meaning_and_embeds_each_capability_once(self) -> None:
        embedder = WordEmbedder()
        retriever = QdrantRetriever(embedder=embedder, mode="dense")
        ranked = await retriever.retrieve("weather", catalog(), limit=1)
        assert capability_ids(ranked) == ["s:tool:forecast"]
        await retriever.retrieve("email", catalog(), limit=1)
        assert len(embedder.documents) == 3
        changed = [*catalog()[:2], tool("s", "forecast", "Weather forecast for a city")]
        await retriever.retrieve("weather", changed, limit=1)
        assert len(embedder.documents) == 4
        await retriever.close()

    @pytest.mark.parametrize(
        "options",
        [{}, {"fusion": "dbsf"}, {"rrf_k": 2}, {"prefetch_limit": 1}],
    )
    async def test_hybrid_fuses_dense_and_sparse_rankings(self, options: dict[str, Any]) -> None:
        retriever = QdrantRetriever(embedder=WordEmbedder(), **options)
        ranked = await retriever.retrieve("send email", catalog(), limit=1)
        assert capability_ids(ranked) == ["s:tool:send_email"]
        await retriever.close()

    async def test_hybrid_queries_without_words_rank_by_meaning(self) -> None:
        embedder = WordEmbedder()
        retriever = QdrantRetriever(embedder=embedder)
        assert len(await retriever.retrieve("the", catalog(), limit=3)) == 3
        assert embedder.queries == ["the"]
        await retriever.close()

    @pytest.mark.parametrize("size", [0, 3])
    async def test_rejects_inconsistent_embeddings(self, size: int) -> None:
        retriever = QdrantRetriever(embedder=WordEmbedder(size=size))
        if size:
            await retriever.retrieve("x", catalog()[:1], limit=1)
            retriever._embedder = WordEmbedder(size=size + 1)
        with pytest.raises(ConfigurationError, match="vectors"):
            await retriever.retrieve("x", catalog(), limit=1)
        await retriever.close()

    async def test_failed_embedding_calls_leave_the_retriever_consistent(self) -> None:
        embedder = WordEmbedder()
        embedder.failures = 1
        retriever = QdrantRetriever(embedder=embedder, max_points=1)
        first, second, third = catalog()
        with pytest.raises(ConnectionError, match="rate limited"):
            await retriever.retrieve("read", [first], limit=1)
        assert retriever._digests == {}
        for _ in range(2):
            ranked = await retriever.retrieve("email", [second, third], limit=1)
            assert capability_ids(ranked) == ["s:tool:send_email"]
        assert set(retriever._digests) <= set(retriever._seen)
        ranked = await retriever.retrieve("read", [first], limit=1)
        assert capability_ids(ranked) == ["s:tool:read_file"]
        await retriever.close()


class TestExternalCollections:
    async def test_a_restarted_retriever_reuses_stored_points(
        self, client: AsyncQdrantClient
    ) -> None:
        embedder = WordEmbedder()
        first = QdrantRetriever(embedder=embedder, client=client, collection_name="caps")
        assert (await first.retrieve("send email", catalog(), limit=1))[0].name == "send_email"
        await first.close()
        assert await client.collection_exists("caps")
        embedded = len(embedder.documents)
        second = QdrantRetriever(embedder=embedder, client=client, collection_name="caps")
        assert (await second.retrieve("read file", catalog(), limit=1))[0].name == "read_file"
        assert len(embedder.documents) == embedded
        assert second.client is client

    async def test_server_collections_index_the_capability_id(
        self, client: AsyncQdrantClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("mcp_capability_router.retrieval._is_local", lambda _: False)
        retriever = QdrantRetriever(client=client)
        with pytest.warns(UserWarning, match="Payload indexes have no effect"):
            await retriever.retrieve("email", catalog(), limit=1)

    async def test_points_without_a_digest_are_reindexed(self, client: AsyncQdrantClient) -> None:
        retriever = QdrantRetriever(client=client)
        await retriever.retrieve("email", catalog(), limit=1)
        key = "s:tool:send_email"
        await client.overwrite_payload(
            retriever.collection_name, payload={"capability_id": key}, points=[_point_id(key)]
        )
        restarted = QdrantRetriever(client=client)
        assert capability_ids(await restarted.retrieve("email", catalog(), limit=1)) == [key]
        assert set(restarted._digests) == {capability.capability_id for capability in catalog()}

    async def test_sparse_mode_accepts_a_hybrid_collection(self, client: AsyncQdrantClient) -> None:
        hybrid = QdrantRetriever(embedder=WordEmbedder(), client=client)
        await hybrid.retrieve("email", catalog(), limit=1)
        sparse = QdrantRetriever(client=client)
        assert capability_ids(await sparse.retrieve("email", catalog(), limit=1)) == [
            "s:tool:send_email"
        ]

    async def test_dense_mode_adopts_the_collection_vector_size(
        self, client: AsyncQdrantClient
    ) -> None:
        await QdrantRetriever(embedder=WordEmbedder(), client=client).retrieve(
            "email", catalog(), limit=1
        )
        shorter = QdrantRetriever(embedder=WordEmbedder(size=3), client=client)
        with pytest.raises(ConfigurationError, match="size is not 8"):
            await shorter.retrieve("weather", [tool("s", "other", "Other")], limit=1)

    @pytest.mark.parametrize(
        ("vectors", "sparse", "mode", "message"),
        [
            ({}, {}, "sparse", "no sparse vector 'sparse' with the IDF modifier"),
            ({}, {"sparse": models.SparseVectorParams()}, "sparse", "IDF modifier"),
            (
                {},
                {"sparse": models.SparseVectorParams(modifier=models.Modifier.IDF)},
                "dense",
                "no dense vector 'dense'",
            ),
        ],
    )
    async def test_rejects_foreign_collections(
        self,
        client: AsyncQdrantClient,
        vectors: dict[str, Any],
        sparse: dict[str, Any],
        mode: str,
        message: str,
    ) -> None:
        await client.create_collection(
            "foreign", vectors_config=vectors, sparse_vectors_config=sparse
        )
        embedder = WordEmbedder() if mode != "sparse" else None
        retriever = QdrantRetriever(
            embedder=embedder,
            mode=mode,  # type: ignore[arg-type]
            client=client,
            collection_name="foreign",
        )
        with pytest.raises(ConfigurationError, match=message):
            await retriever.retrieve("x", catalog(), limit=1)
