"""Embedding and reranking models for the retrieval examples.

`load_embedder` reads MCP_ROUTER_EXAMPLE_EMBEDDINGS, and `load_reranker` reads
MCP_ROUTER_EXAMPLE_RERANKER:

    # A LangChain embedding model, as for `langchain.embeddings.init_embeddings`.
    MCP_ROUTER_EXAMPLE_EMBEDDINGS=openai:text-embedding-3-small   # and OPENAI_API_KEY

    # A sentence-transformers model on this machine or on the Hugging Face Hub,
    # such as BAAI/bge-m3 and BAAI/bge-reranker-v2-m3. Relative paths are
    # resolved from the repository root.
    MCP_ROUTER_EXAMPLE_EMBEDDINGS=sentence-transformers:models/bge-m3
    MCP_ROUTER_EXAMPLE_RERANKER=models/bge-reranker-v2-m3

LangChain models need the `langchain` extra, and sentence-transformers models
the `models` dependency group: `uv sync --all-extras --group examples --group models`.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from retrievalloom.contracts.component import ComponentInfo, make_info
from retrievalloom.contracts.models import RerankerABC, RerankItem, RerankScore

from mcp_capability_router import Embedder

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parent.parent
LOCAL = "sentence-transformers:"


def _locate(model: str) -> str:
    """Resolve a model directory from the repository root, or keep a Hub name."""
    path = ROOT / model
    return str(path) if path.is_dir() else model


def _quiet() -> None:
    from transformers.utils import logging

    logging.disable_progress_bar()
    logging.set_verbosity_error()


class SentenceTransformerEmbedder(Embedder):
    """Embeds texts with a sentence-transformers model, such as BAAI/bge-m3."""

    def __init__(self, model: str) -> None:
        from sentence_transformers import SentenceTransformer

        _quiet()
        self.model = SentenceTransformer(_locate(model), device="cpu")

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors: Any = self.model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return await asyncio.to_thread(self._encode, list(texts))

    async def embed_query(self, text: str) -> Sequence[float]:
        [vector] = await asyncio.to_thread(self._encode, [text])
        return vector


class CrossEncoderReranker(RerankerABC):
    """Reranks with a sentence-transformers cross-encoder, such as BAAI/bge-reranker-v2-m3."""

    def __init__(self, model: str) -> None:
        from sentence_transformers import CrossEncoder

        _quiet()
        self.model = CrossEncoder(_locate(model), device="cpu")
        self._info = make_info(
            component="reranker",
            implementation="sentence-transformers",
            version="1",
            model_identity=f"cross-encoder:{model}",
        )

    @property
    def info(self) -> ComponentInfo:
        return self._info

    def _score(self, query: str, texts: list[str]) -> list[float]:
        scores: Any = self.model.predict([(query, text) for text in texts])
        return [float(score) for score in scores]

    async def rerank(self, query: str, items: Sequence[RerankItem]) -> Sequence[RerankScore]:
        if not items:
            return []
        scores = await asyncio.to_thread(self._score, query, [item.text for item in items])
        return [
            RerankScore(item_id=item.item_id, score=score)
            for item, score in zip(items, scores, strict=True)
        ]


def load_embedder() -> Embedder | None:
    """Return the embedder named by MCP_ROUTER_EXAMPLE_EMBEDDINGS, if it is set."""
    model = os.environ.get("MCP_ROUTER_EXAMPLE_EMBEDDINGS")
    if not model:
        return None
    if model.startswith(LOCAL):
        return SentenceTransformerEmbedder(model.removeprefix(LOCAL))
    from langchain.embeddings import init_embeddings

    from mcp_capability_router.integrations.langchain import LangChainEmbedder

    return LangChainEmbedder(init_embeddings(model))


def load_reranker() -> RerankerABC | None:
    """Return the reranker named by MCP_ROUTER_EXAMPLE_RERANKER, if it is set."""
    model = os.environ.get("MCP_ROUTER_EXAMPLE_RERANKER")
    return CrossEncoderReranker(model) if model else None
