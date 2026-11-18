"""The default RetrievalLoom retriever: BM25 keyword ranking, embeddings, and reranking."""

from __future__ import annotations

import gc
import re
from typing import TYPE_CHECKING, Any

import pytest
import retrievalloom
from retrievalloom import (
    Components,
    EngineConfig,
    EngineResources,
    In,
    IngestionConfig,
    IngestionLimits,
    Not,
)
from retrievalloom.contracts.component import ComponentInfo, make_info
from retrievalloom.contracts.models import RerankerABC, RerankItem, RerankScore
from retrievalloom.index.text import SimpleTokenizer

from mcp_capability_router import (
    CapabilityRetriever,
    ConfigurationError,
    Embedder,
    LoomRetriever,
    Tool,
    document_text,
)
from mcp_capability_router.retrieval import _CapabilityTokenizer, _document_id, _terms, _words
from tests.support import capability_ids, resource, tool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence
    from pathlib import Path

VOCABULARY = ("read", "file", "send", "email", "weather", "forecast", "notes")


class WordEmbedder(Embedder):
    """Embeds texts as bags of known words, so similarity is word overlap."""

    def __init__(self, size: int | None = None) -> None:
        self.documents: list[str] = []
        self.queries: list[str] = []
        self.size = size

    @staticmethod
    def vector(text: str) -> list[float]:
        words = set(re.findall(r"[a-z]+", text.lower()))
        return [1.0 if word in words else 0.0 for word in VOCABULARY] + [0.01]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [self.vector(text)[: self.size] for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self.vector(text)[: self.size]


class LengthReranker(RerankerABC):
    """Scores shorter texts higher, whatever the query."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def info(self) -> ComponentInfo:
        return make_info(component="reranker", implementation="length", version="1")

    async def rerank(self, query: str, items: Sequence[RerankItem]) -> Sequence[RerankScore]:
        self.calls += 1
        return [RerankScore(item_id=item.item_id, score=-len(item.text)) for item in items]


def catalog() -> list[Tool]:
    return [
        tool("s", "read_file", "Read a file"),
        tool("s", "send_email", "Send an email"),
        tool("s", "forecast", "Weather forecast"),
    ]


@pytest.fixture
async def retriever() -> AsyncIterator[LoomRetriever]:
    instance = LoomRetriever()
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

    async def test_tokenizer_weighs_document_fields_and_dedupes_queries(self) -> None:
        tokenizer = _CapabilityTokenizer()
        capability = tool("s", "search", "Find records", tags=frozenset({"lookup"}))
        text = document_text(capability)
        tokenizer.add(text, capability)
        tokenizer.add(text, capability)
        [document, query] = await tokenizer.tokenize([text, "search search records"])
        assert document.count("search") == 6
        assert document.count("lookup") == 4
        assert document.count("record") == 2
        assert document.count("~recor") == 1
        assert query == ["search", "~searc", "record", "~recor"]
        assert tokenizer.info.name == "mcp-capability-router"
        tokenizer.discard(text)
        assert (await tokenizer.tokenize([text]))[0] == document
        tokenizer.discard(text)
        assert (await tokenizer.tokenize([text]))[0] != document

    def test_document_ids_are_bounded_digests(self) -> None:
        key = "s:resource:" + "x" * 1000
        assert len(_document_id(key)) == 64
        assert _document_id(key) != _document_id("s:tool:x")


class TestConfiguration:
    def test_defaults(self) -> None:
        retriever = LoomRetriever()
        assert isinstance(retriever, CapabilityRetriever)
        assert retriever.engine is None
        assert (retriever.scope.tenant_id, retriever.scope.collection) == (
            "mcp-capability-router",
            "capabilities",
        )
        assert LoomRetriever(tenant_id="t", collection="c").scope.collection == "c"

    @pytest.mark.parametrize(
        ("arguments", "message"),
        [
            ({"embedder": object()}, "does not subclass Embedder"),
            ({"reranker": object()}, "does not subclass retrievalloom RerankerABC"),
            ({"components": object()}, "is not a retrievalloom Components"),
            ({"config": object()}, "is not a retrievalloom EngineConfig"),
            ({"resources": object()}, "is not a retrievalloom EngineResources"),
            (
                {"embedder": WordEmbedder(), "components": Components(embedding=object())},  # type: ignore[arg-type]
                "embedder either directly or as components.embedding",
            ),
            (
                {"reranker": LengthReranker(), "components": Components(reranker=object())},  # type: ignore[arg-type]
                "reranker either directly or as components.reranker",
            ),
            ({"tenant_id": ""}, "invalid tenant_id"),
            ({"collection": " x "}, "invalid tenant_id"),
            ({"fetch_limit": 0}, "fetch_limit"),
            ({"max_documents": True}, "max_documents"),
        ],
    )
    def test_rejects_invalid_arguments(self, arguments: dict[str, Any], message: str) -> None:
        with pytest.raises(ConfigurationError, match=message):
            LoomRetriever(**arguments)

    async def test_validates_the_limit_and_skips_empty_candidates(
        self, retriever: LoomRetriever
    ) -> None:
        with pytest.raises(ConfigurationError, match="limit"):
            await retriever.retrieve("x", catalog(), limit=0)
        assert await retriever.retrieve("x", [], limit=3) == []
        assert retriever.engine is None

    @pytest.mark.parametrize("method", ["initialize", "ingest", "retrieve"])
    async def test_translates_engine_configuration_errors(
        self, method: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fail(*_: object, **__: object) -> None:
            msg = "unsupported"
            raise retrievalloom.ConfigurationError(msg)

        monkeypatch.setattr(retrievalloom.RetrievalEngine, method, fail)
        retriever = LoomRetriever()
        with pytest.raises(ConfigurationError, match="unsupported"):
            await retriever.retrieve("email", catalog(), limit=1)
        indexed = method == "retrieve"
        assert bool(retriever._texts) is indexed
        assert bool(retriever._tokenizer._documents) is indexed
        assert (retriever.engine is not None) is (method != "initialize")
        await retriever.close()

    async def test_a_given_config_replaces_the_defaults(self) -> None:
        retriever = LoomRetriever(config=EngineConfig())
        ranked = await retriever.retrieve("email", catalog(), limit=1)
        assert capability_ids(ranked) == ["s:tool:send_email"]
        await retriever.close()


class TestKeyword:
    async def test_matches_words_plurals_and_stems_but_not_substrings(
        self, retriever: LoomRetriever
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
        self, retriever: LoomRetriever
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

    async def test_rare_words_outweigh_common_words(self, retriever: LoomRetriever) -> None:
        candidates = [tool("s", f"file_tool_{index}", "file utility") for index in range(9)]
        candidates.append(tool("s", "archive", "file archive utility"))
        ranked = await retriever.retrieve("archive file", candidates, limit=3)
        assert ranked[0].capability_id == "s:tool:archive"

    async def test_resource_uris_and_titles_are_searchable(self, retriever: LoomRetriever) -> None:
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
        self, retriever: LoomRetriever
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

    async def test_ties_are_broken_by_capability_id(self, retriever: LoomRetriever) -> None:
        names = ["delta", "alpha", "echo", "charlie", "bravo"]
        candidates = [tool("s", name, "search records") for name in names]
        ranked = await retriever.retrieve("search", candidates, limit=2)
        assert capability_ids(ranked) == ["s:tool:alpha", "s:tool:bravo"]
        candidates.append(tool("s", "search", "search"))
        ranked = await retriever.retrieve("search", list(reversed(candidates)), limit=3)
        assert capability_ids(ranked) == ["s:tool:search", "s:tool:alpha", "s:tool:bravo"]

    async def test_capabilities_with_the_same_text_are_all_returned(
        self, retriever: LoomRetriever
    ) -> None:
        candidates = [tool("b", "search", "Search"), tool("a", "search", "Search")]
        ranked = await retriever.retrieve("search", candidates, limit=2)
        assert capability_ids(ranked) == ["a:tool:search", "b:tool:search"]

    async def test_only_the_given_candidates_are_returned(
        self, retriever: LoomRetriever, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await retriever.retrieve("email", catalog(), limit=3)
        engine = retriever.engine
        assert engine is not None
        filters: list[object] = []
        search = engine.retrieve

        async def spy(*args: Any, **kwargs: Any) -> Any:
            filters.append(kwargs["filters"])
            return await search(*args, **kwargs)

        monkeypatch.setattr(engine, "retrieve", spy)
        assert await retriever.retrieve("email", catalog()[:1], limit=3) == []
        ranked = await retriever.retrieve("email file", catalog()[:2], limit=3)
        assert sorted(capability_ids(ranked)) == ["s:tool:read_file", "s:tool:send_email"]
        await retriever.retrieve("email", catalog(), limit=3)
        first, second, third = filters
        assert isinstance(first, In)
        assert first.values == (_document_id("s:tool:read_file"),)
        assert isinstance(second, Not)
        assert second.clause == In(field="_id", values=(_document_id("s:tool:forecast"),))
        assert third is None

    async def test_changed_capabilities_are_reindexed(self, retriever: LoomRetriever) -> None:
        assert capability_ids(await retriever.retrieve("old", [tool("s", "x", "old")], limit=1))
        changed = [tool("s", "x", "new")]
        assert capability_ids(await retriever.retrieve("new", changed, limit=1)) == ["s:tool:x"]
        assert await retriever.retrieve("old", changed, limit=1) == []
        assert list(retriever._tokenizer._documents) == [document_text(changed[0])]

    async def test_rejected_capabilities_are_not_indexed(self) -> None:
        config = EngineConfig(ingestion=IngestionConfig(limits=IngestionLimits(max_text_chars=40)))
        retriever = LoomRetriever(config=config)
        short, long = tool("s", "mail", "Mail"), tool("s", "mail_all", "Mail " * 20)
        ranked = await retriever.retrieve("mail", [short, long], limit=2)
        assert capability_ids(ranked) == ["s:tool:mail"]
        assert set(retriever._texts) == {"s:tool:mail"}
        await retriever.retrieve("mail", [tool("s", "mail", "Mail " * 20)], limit=1)
        assert retriever._texts["s:tool:mail"] == document_text(short)
        await retriever.close()

    async def test_capabilities_are_ingested_in_batches(self) -> None:
        config = EngineConfig(
            ingestion=IngestionConfig(limits=IngestionLimits(max_documents_per_call=2))
        )
        retriever = LoomRetriever(config=config)
        ranked = await retriever.retrieve("weather", catalog(), limit=1)
        assert capability_ids(ranked) == ["s:tool:forecast"]
        assert len(retriever._texts) == 3
        await retriever.close()

    async def test_least_recently_seen_capabilities_are_evicted(self) -> None:
        retriever = LoomRetriever(max_documents=2)
        first, second, third = catalog()
        await retriever.retrieve("x", [first, second], limit=2)
        await retriever.retrieve("x", [third], limit=1)
        assert set(retriever._texts) == {second.capability_id, third.capability_id}
        ranked = await retriever.retrieve("read email", [first, second], limit=2)
        assert capability_ids(ranked) == ["s:tool:read_file", "s:tool:send_email"]
        crowded = LoomRetriever(max_documents=1)
        assert len(await crowded.retrieve("read email forecast", catalog(), limit=3)) == 3
        assert len(crowded._texts) == 3
        await retriever.close()
        await crowded.close()

    async def test_close_releases_the_engine(self) -> None:
        retriever = LoomRetriever()
        await retriever.retrieve("email", catalog(), limit=1)
        first = retriever.engine
        await retriever.close()
        await retriever.close()
        assert retriever.engine is None
        assert retriever._texts == {}
        assert capability_ids(await retriever.retrieve("email", catalog(), limit=1)) == [
            "s:tool:send_email"
        ]
        assert retriever.engine is not first
        await retriever.close()

    async def test_long_queries_are_truncated(self, retriever: LoomRetriever) -> None:
        ranked = await retriever.retrieve("email " + "x" * 10_000, catalog(), limit=1)
        assert capability_ids(ranked) == ["s:tool:send_email"]


class TestEmbeddings:
    async def test_ranks_by_meaning_and_embeds_each_capability_once(self) -> None:
        embedder = WordEmbedder()
        retriever = LoomRetriever(embedder=embedder)
        ranked = await retriever.retrieve("forecast weather", catalog(), limit=1)
        assert capability_ids(ranked) == ["s:tool:forecast"]
        await retriever.retrieve("email", catalog(), limit=1)
        assert len(embedder.documents) == 3
        changed = [*catalog()[:2], tool("s", "forecast", "Weather forecast for a city")]
        await retriever.retrieve("weather", changed, limit=1)
        assert len(embedder.documents) == 4
        await retriever.close()

    async def test_queries_without_words_rank_by_meaning(self) -> None:
        embedder = WordEmbedder()
        retriever = LoomRetriever(embedder=embedder)
        assert len(await retriever.retrieve("the", catalog(), limit=3)) == 3
        assert embedder.queries[-1] == "the"
        await retriever.close()

    async def test_rejects_an_empty_embedding(self) -> None:
        retriever = LoomRetriever(embedder=WordEmbedder(size=0))
        with pytest.raises(ConfigurationError, match="empty vector"):
            await retriever.retrieve("x", catalog(), limit=1)

    # qdrant-client's local persistence leaks the probe connection it opens on
    # first use, in every process that keeps a Qdrant collection in files.
    @pytest.mark.filterwarnings(
        "ignore:Exception ignored while finalizing database connection"
        ":pytest.PytestUnraisableExceptionWarning"
    )
    async def test_a_restarted_retriever_reuses_stored_documents(self, tmp_path: Path) -> None:
        embedder = WordEmbedder()
        resources = EngineResources(data_dir=tmp_path)
        first = LoomRetriever(embedder=embedder, resources=resources)
        assert capability_ids(await first.retrieve("send email", catalog(), limit=1)) == [
            "s:tool:send_email"
        ]
        await first.close()
        embedded = len(embedder.documents)
        second = LoomRetriever(embedder=embedder, resources=resources)
        assert capability_ids(await second.retrieve("read file", catalog(), limit=1)) == [
            "s:tool:read_file"
        ]
        assert len(embedder.documents) == embedded
        await second.close()


class TestComponents:
    async def test_a_reranker_reorders_the_matches(self) -> None:
        reranker = LengthReranker()
        retriever = LoomRetriever(reranker=reranker)
        candidates = [tool("s", "file_long", "File " * 10), tool("s", "file", "File")]
        ranked = await retriever.retrieve("file", candidates, limit=2)
        assert capability_ids(ranked) == ["s:tool:file", "s:tool:file_long"]
        assert reranker.calls == 1
        await retriever.close()

    async def test_given_components_are_used_and_filtered(self) -> None:
        tokenizer = SimpleTokenizer()
        retriever = LoomRetriever(components=Components(tokenizer=tokenizer))
        ranked = await retriever.retrieve("email", catalog(), limit=3)
        assert capability_ids(ranked) == ["s:tool:send_email"]
        assert await retriever.retrieve("navigation", [tool("s", "navigate")], limit=1) == []
        await retriever.close()

    @pytest.mark.filterwarnings(
        "ignore:Exception ignored while finalizing database connection"
        "|Exception ignored in. <sqlite3.Connection"
        ":pytest.PytestUnraisableExceptionWarning"
    )
    async def test_a_reranker_in_the_components_enables_reranking(self) -> None:
        reranker = LengthReranker()
        retriever = LoomRetriever(components=Components(reranker=reranker))
        await retriever.retrieve("email", catalog(), limit=1)
        assert reranker.calls == 1
        await retriever.close()
        del retriever
        # Run SQLite's finalizers before this test's warning filter ends.
        gc.collect()
