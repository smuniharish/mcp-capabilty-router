from __future__ import annotations

import pytest

from mcp_capability_router import (
    CapabilityRetriever,
    ConfigurationError,
    KeywordRetriever,
    Tool,
)
from mcp_capability_router.retrieval import _words
from tests.support import capability_ids, resource, tool


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
def test_words_split_identifiers_and_prose(text: str, words: list[str]) -> None:
    assert list(_words(text)) == words


async def test_retriever_implements_the_contract() -> None:
    assert isinstance(KeywordRetriever(), CapabilityRetriever)


async def test_matches_whole_words_and_prefixes_but_not_substrings() -> None:
    retriever = KeywordRetriever()
    candidates = [
        tool("s", "read_text_file", "Read a file from disk"),
        tool("s", "thread_dump", "Dump the threads of a process"),
        tool("s", "navigate", "Open a page in the browser"),
    ]
    assert capability_ids(await retriever.retrieve("read", candidates, limit=5)) == [
        "s:tool:read_text_file"
    ]
    assert capability_ids(await retriever.retrieve("nav", candidates, limit=5)) == [
        "s:tool:navigate"
    ]
    assert capability_ids(await retriever.retrieve("files", candidates, limit=5)) == [
        "s:tool:read_text_file"
    ]
    assert capability_ids(
        await retriever.retrieve("navigation", candidates, limit=5)
    ) == ["s:tool:navigate"]
    assert await retriever.retrieve("re", candidates, limit=5) == []


async def test_whole_words_outrank_prefixes_and_shared_stems() -> None:
    retriever = KeywordRetriever()
    candidates = [
        tool("s", "close_ticket", "Close a ticket", tags=frozenset({"tickets"})),
        tool("s", "search_tickets", "Search tickets", tags=frozenset({"tickets"})),
        tool("s", "read_multiple_files", "Read several files"),
        tool("s", "read_file", "Read one file"),
    ]
    assert capability_ids(
        await retriever.retrieve("find tickets about the VPN", candidates, limit=2)
    ) == ["s:tool:search_tickets", "s:tool:close_ticket"]
    assert capability_ids(await retriever.retrieve("ticket", candidates, limit=2)) == [
        "s:tool:close_ticket",
        "s:tool:search_tickets",
    ]
    assert capability_ids(
        await retriever.retrieve("read file", candidates, limit=2)
    ) == [
        "s:tool:read_file",
        "s:tool:read_multiple_files",
    ]


async def test_name_matches_outrank_tag_and_description_matches() -> None:
    retriever = KeywordRetriever()
    candidates = [
        tool("s", "c_describes", "Search everything"),
        tool("s", "b_tagged", tags=frozenset({"search"})),
        tool("s", "a_search_named", "Search by name, then search again"),
    ]
    assert capability_ids(await retriever.retrieve("search", candidates, limit=3)) == [
        "s:tool:a_search_named",
        "s:tool:b_tagged",
        "s:tool:c_describes",
    ]


async def test_rare_words_outweigh_common_words() -> None:
    retriever = KeywordRetriever()
    candidates = [tool("s", f"file_tool_{index}", "file utility") for index in range(9)]
    candidates.append(tool("s", "archive", "file archive utility"))
    ranked = await retriever.retrieve("archive file", candidates, limit=3)
    assert ranked[0].capability_id == "s:tool:archive"


async def test_resource_uris_and_titles_are_searchable() -> None:
    retriever = KeywordRetriever()
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


async def test_stop_words_and_empty_queries_list_candidates_by_id() -> None:
    retriever = KeywordRetriever()
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


async def test_ties_are_broken_by_capability_id_and_limit_is_applied() -> None:
    retriever = KeywordRetriever()
    candidates = [tool("s", name, "search") for name in ("delta", "alpha", "charlie")]
    ranked = await retriever.retrieve("search", candidates, limit=2)
    assert capability_ids(ranked) == ["s:tool:alpha", "s:tool:charlie"]


async def test_invalid_limits_are_rejected() -> None:
    with pytest.raises(ConfigurationError):
        await KeywordRetriever().retrieve("x", [], limit=0)


async def test_index_cache_is_reused_rebuilt_on_change_and_pruned() -> None:
    retriever = KeywordRetriever()
    original = tool("s", "x", "old words")
    await retriever.retrieve("old", [original], limit=1)
    cached = retriever._cache["s:tool:x"]
    await retriever.retrieve("old", [original], limit=1)
    assert retriever._cache["s:tool:x"] is cached
    changed = Tool(capability_id="s:tool:x", server_id="s", name="x", description="new")
    assert capability_ids(await retriever.retrieve("new", [changed], limit=1)) == [
        "s:tool:x"
    ]
    assert retriever._cache["s:tool:x"] is not cached

    many = [tool("s", f"t{index}", "bulk") for index in range(1100)]
    await retriever.retrieve("bulk", many, limit=1)
    assert len(retriever._cache) == 1101
    await retriever.retrieve("bulk", many[:10], limit=1)
    assert len(retriever._cache) == 10
