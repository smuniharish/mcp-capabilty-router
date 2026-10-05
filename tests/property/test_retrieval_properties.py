"""Properties of capability retrieval."""

from __future__ import annotations

import asyncio
import random

from hypothesis import given
from hypothesis import strategies as st

from mcp_capability_router import KeywordRetriever, Tool
from mcp_capability_router.retrieval import _words

WORDS = st.sampled_from(
    ["read", "file", "files", "search", "send", "email", "thread", "navigate", "notes"]
)
TEXT = st.lists(WORDS, max_size=6).map(" ".join)


@st.composite
def catalogs(draw: st.DrawFn) -> list[Tool]:
    names = draw(
        st.lists(
            st.from_regex(r"[a-z][a-z_]{0,12}", fullmatch=True),
            unique=True,
            max_size=25,
        )
    )
    return [
        Tool(
            capability_id=f"s:tool:{name}",
            server_id="s",
            name=name,
            description=draw(TEXT),
            tags=frozenset(draw(st.lists(WORDS, max_size=2))),
        )
        for name in names
    ]


def retrieve(query: str, candidates: list[Tool], limit: int) -> list[str]:
    ranked = asyncio.run(KeywordRetriever().retrieve(query, candidates, limit=limit))
    return [capability.capability_id for capability in ranked]


@given(st.text(max_size=60))
def test_words_are_lowercase_and_separator_free(text: str) -> None:
    for word in _words(text):
        assert word
        assert word == word.casefold() or not word.isascii()
        assert not any(character in word for character in " _-./:")


@given(catalogs(), TEXT, st.integers(min_value=1, max_value=30))
def test_results_are_unique_bounded_subsets(
    candidates: list[Tool], query: str, limit: int
) -> None:
    result = retrieve(query, candidates, limit)
    assert len(result) == len(set(result)) <= limit
    assert set(result) <= {capability.capability_id for capability in candidates}


@given(catalogs(), TEXT, st.integers(min_value=1, max_value=30), st.randoms())
def test_ranking_ignores_candidate_order(
    candidates: list[Tool], query: str, limit: int, rng: random.Random
) -> None:
    shuffled = list(candidates)
    rng.shuffle(shuffled)
    assert retrieve(query, candidates, limit) == retrieve(query, shuffled, limit)


@given(catalogs(), st.integers(min_value=1, max_value=30))
def test_queries_without_words_list_candidates_by_id(
    candidates: list[Tool], limit: int
) -> None:
    expected = sorted(capability.capability_id for capability in candidates)[:limit]
    assert retrieve("the of to", candidates, limit) == expected


@given(catalogs(), TEXT, st.integers(min_value=1, max_value=10))
def test_smaller_limits_return_prefixes(
    candidates: list[Tool], query: str, limit: int
) -> None:
    longer = retrieve(query, candidates, limit + 5)
    assert retrieve(query, candidates, limit) == longer[:limit]
