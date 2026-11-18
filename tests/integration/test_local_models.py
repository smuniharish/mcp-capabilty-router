"""Rank capabilities with real embedding and reranking models.

Set MCP_ROUTER_LIVE_MODELS to a directory that holds BAAI/bge-m3 and
BAAI/bge-reranker-v2-m3, such as the repository's gitignored `models`
directory, and install the `models` dependency group:

    uv sync --all-extras --group examples --group models
    MCP_ROUTER_LIVE_MODELS=models uv run pytest -m live
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mcp_capability_router import Embedder, LoomRetriever, Tool

if TYPE_CHECKING:
    from retrievalloom.contracts.models import RerankerABC

ROOT = Path(__file__).resolve().parents[2]
MODELS = os.environ.get("MCP_ROUTER_LIVE_MODELS", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.timeout(600),
    pytest.mark.skipif(not MODELS, reason="set MCP_ROUTER_LIVE_MODELS to run"),
]


def tool(name: str, description: str) -> Tool:
    return Tool(capability_id=f"s:tool:{name}", server_id="s", name=name, description=description)


CATALOG = [
    tool("issue_refund", "Return a payment to the card that paid an invoice"),
    tool("search_docs", "Full-text search over the product manuals"),
    tool("lookup_contact", "Find the people who work at an account"),
    tool("forecast", "Weather forecast for a city"),
]
REQUESTS = {
    "give a customer their money back": "s:tool:issue_refund",
    "where are the setup instructions": "s:tool:search_docs",
    "who is our person at Acme": "s:tool:lookup_contact",
}


@pytest.fixture(scope="module")
def models() -> tuple[Embedder, RerankerABC]:
    pytest.importorskip("sentence_transformers")
    sys.path.insert(0, str(ROOT / "examples"))
    try:
        import retrieval_models
    finally:
        sys.path.remove(str(ROOT / "examples"))
    directory = Path(MODELS) if Path(MODELS).is_absolute() else ROOT / MODELS
    return (
        retrieval_models.SentenceTransformerEmbedder(str(directory / "bge-m3")),
        retrieval_models.CrossEncoderReranker(str(directory / "bge-reranker-v2-m3")),
    )


@pytest.mark.parametrize("rerank", [False, True], ids=["embeddings", "reranked"])
async def test_requests_find_tools_that_share_no_words(
    models: tuple[Embedder, RerankerABC], rerank: bool
) -> None:
    embedder, reranker = models
    retriever = LoomRetriever(embedder=embedder, reranker=reranker if rerank else None)
    try:
        for request, expected in REQUESTS.items():
            [best] = await retriever.retrieve(request, CATALOG, limit=1)
            assert best.capability_id == expected, request
    finally:
        await retriever.close()
