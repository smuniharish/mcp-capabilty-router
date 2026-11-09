"""Retrievers that rank candidate capabilities against a query."""

from __future__ import annotations

import asyncio
import heapq
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore

from ._internal.concurrency import gather_or_cancel
from ._internal.naming import validate_limit
from .contracts import CapabilityRetriever
from .errors import ConfigurationError
from .models import Capability, Resource

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

_SEPARATORS = re.compile(r"[\W_]+")
_CAMEL_CASE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    }
)
_NAME_WEIGHT = 3.0
_TAG_WEIGHT = 2.0
_TEXT_WEIGHT = 1.0
_MIN_PREFIX = 3
_MIN_STEM = 4


def _words(text: str) -> Iterator[str]:
    """Split identifiers and prose into lowercase words.

    `read_text_file`, `readTextFile`, and `read-text-file` all yield `read`,
    `text`, and `file`.
    """
    for chunk in _SEPARATORS.split(text):
        if chunk.isascii():
            yield from (word.lower() for word in _CAMEL_CASE.findall(chunk))
        else:
            yield chunk.casefold()


def _query_terms(query: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(w for w in _words(query) if w not in _STOP_WORDS))


@dataclass(frozen=True, slots=True)
class _Index:
    """The best match weight of every word, and word prefix, of one capability.

    A prefix weighs its field weight times the share of the word it covers, so a
    whole word outweighs a prefix of a longer word in the same field.
    """

    capability: Capability
    weights: dict[str, float]

    @classmethod
    def build(cls, capability: Capability) -> _Index:
        fields = (
            (_NAME_WEIGHT, f"{capability.name} {capability.title or ''}"),
            (_TAG_WEIGHT, " ".join(sorted(capability.tags))),
            (
                _TEXT_WEIGHT,
                f"{capability.description} "
                f"{capability.uri if isinstance(capability, Resource) else ''}",
            ),
        )
        weights: dict[str, float] = {}
        for weight, text in fields:
            for word in _words(text):
                length = len(word)
                for end in range(min(_MIN_PREFIX, length), length + 1):
                    key = word[:end]
                    value = weight * end / length
                    if weights.get(key, 0.0) < value:
                        weights[key] = value
        return cls(capability, weights)


def _lookup_keys(term: str) -> tuple[tuple[str, float], ...]:
    """Return the keys that can match `term`, with the share of `term` each keeps.

    The term itself matches every word it is a prefix of; each of its own prefixes
    of at least 4 characters matches the words that share that stem, discounted by
    the share of the term that the stem keeps.
    """
    length = len(term)
    return (
        (term, 1.0),
        *((term[:end], end / length) for end in range(length - 1, _MIN_STEM - 1, -1)),
    )


def _positive(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        msg = f"{name} must be a positive integer, got {value!r}"
        raise ConfigurationError(msg)
    return value


class KeywordRetriever(CapabilityRetriever):
    """Ranks capabilities by the query words they contain.

    The default retriever of `MCPRuntime`. It needs no model and no service, is
    deterministic, and handles tens of thousands of capabilities per query.

    Matching works on words: identifiers such as `read_text_file` or `getWeather`
    are split into words. A query word matches a capability word when it is a
    prefix of that word (at least 3 characters), or when both words start with
    the same 4 or more characters. So `nav` matches `navigate`, `navigation`
    matches `navigate`, and `files` matches `file`, while `read` does not match
    `thread`. Common English stop words are ignored.

    A match in the name or title weighs 3, in a tag 2, and in the description or
    resource URI 1. Partial matches weigh less: a prefix in proportion to the
    share of the word it covers, and a shared stem in proportion to the share of
    both words it covers. So for the query `tickets`, `search_tickets` outranks
    `close_ticket`, and for the query `ticket`, the order is reversed.
    Each query word is weighted by its inverse document frequency among the
    candidates, so rare words count more than words that most capabilities
    share. Ties are broken by capability ID. A query without usable words
    returns the candidates in capability-ID order.
    """

    def __init__(self) -> None:
        """Create a retriever with an empty index cache."""
        self._cache: dict[str, _Index] = {}

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        """Return at most `limit` of `candidates` that match `query`, best first.

        Raises:
            ConfigurationError: If `limit` is not a positive integer.
        """
        validate_limit(limit)
        terms = _query_terms(query)
        if not terms:
            return heapq.nsmallest(
                limit, candidates, key=lambda capability: capability.capability_id
            )
        keys = [_lookup_keys(term) for term in terms]
        matches: list[tuple[Capability, list[float]]] = []
        frequencies = [0] * len(terms)
        for capability in candidates:
            weights = self._index(capability).weights
            row: list[float] | None = None
            for position, term_keys in enumerate(keys):
                best = 0.0
                for key, share in term_keys:
                    weight = weights.get(key, 0.0) * share
                    if weight > best:
                        best = weight
                if best:
                    if row is None:
                        row = [0.0] * len(keys)
                    row[position] = best
                    frequencies[position] += 1
            if row is not None:
                matches.append((capability, row))
        self._prune(candidates)
        total = len(candidates)
        idf = [math.log1p(total / frequency) if frequency else 0.0 for frequency in frequencies]
        best_matches = heapq.nsmallest(
            limit,
            matches,
            key=lambda match: (
                -sum(weight * factor for weight, factor in zip(match[1], idf, strict=True)),
                match[0].capability_id,
            ),
        )
        return [capability for capability, _ in best_matches]

    def _index(self, capability: Capability) -> _Index:
        entry = self._cache.get(capability.capability_id)
        if entry is None or (entry.capability is not capability and entry.capability != capability):
            entry = _Index.build(capability)
            self._cache[capability.capability_id] = entry
        return entry

    def _prune(self, candidates: Sequence[Capability]) -> None:
        """Drop cached indexes of capabilities that are no longer candidates."""
        if len(self._cache) > max(1024, 2 * len(candidates)):
            current = {capability.capability_id for capability in candidates}
            self._cache = {key: entry for key, entry in self._cache.items() if key in current}


def _document_text(capability: Capability) -> str:
    name = " ".join(_words(capability.name)) or capability.name
    lines = [f"{capability.title or name} ({capability.type}: {capability.name})"]
    if capability.description:
        lines.append(capability.description)
    if capability.tags:
        lines.append("Tags: " + ", ".join(sorted(capability.tags)))
    if isinstance(capability, Resource):
        lines.append(f"URI: {capability.uri}")
    return "\n".join(lines)


class EmbeddingRetriever(CapabilityRetriever):
    """Ranks capabilities by semantic similarity, using any LangChain embeddings.

    Capabilities are embedded once and re-embedded only when their text changes.
    The vectors live in a LangChain vector store: an `InMemoryVectorStore` by
    default, or any store such as pgvector, Qdrant, or Chroma, which lets several
    processes share the vectors and a restarted process reuse them instead of
    embedding every capability again. Each query embeds the query text and returns
    the most similar candidates. A LangChain document compressor, such as a
    cross-encoder reranker, can re-rank the best `fetch_k` matches.

    Example:
        ```python
        from langchain_openai import OpenAIEmbeddings

        retriever = EmbeddingRetriever(OpenAIEmbeddings(model="text-embedding-3-small"))
        runtime = MCPRuntime(retriever=retriever)
        ```
    """

    def __init__(
        self,
        embeddings: Embeddings | None = None,
        *,
        vector_store: VectorStore | None = None,
        reranker: BaseDocumentCompressor | None = None,
        fetch_k: int = 20,
        max_documents: int = 50_000,
    ) -> None:
        """Create a retriever.

        Args:
            embeddings: The embedding model; the `embeddings` of `vector_store`
                when `None`.
            vector_store: Where the capability vectors are stored; an
                `InMemoryVectorStore` of `embeddings` when `None`. The retriever
                adds, replaces, and deletes documents whose IDs are capability IDs,
                so give it a store, or a collection, of its own.
            reranker: An optional document compressor that re-ranks the matches.
            fetch_k: Number of matches handed to the reranker; ignored without one.
            max_documents: Number of capability vectors to keep. When exceeded, the
                vectors of the capabilities seen least recently are dropped; the
                candidates of the current query are always kept.

        Raises:
            ConfigurationError: If neither `embeddings` nor `vector_store` is
                given, or `fetch_k` or `max_documents` is not positive.
        """
        self._fetch_k = _positive("fetch_k", fetch_k)
        self._max_documents = _positive("max_documents", max_documents)
        if vector_store is not None and not isinstance(vector_store, VectorStore):
            msg = f"vector_store {vector_store!r} does not subclass VectorStore"
            raise ConfigurationError(msg)
        if embeddings is not None and not isinstance(embeddings, Embeddings):
            msg = f"embeddings {embeddings!r} does not subclass Embeddings"
            raise ConfigurationError(msg)
        if vector_store is None:
            if embeddings is None:
                msg = "EmbeddingRetriever needs embeddings or a vector_store"
                raise ConfigurationError(msg)
            vector_store = InMemoryVectorStore(embeddings)
        self._store = vector_store
        self._reranker = reranker
        self._texts: dict[str, str] = {}
        self._seen: dict[str, int] = {}
        self._queries = 0
        self._lock = asyncio.Lock()

    @property
    def vector_store(self) -> VectorStore:
        """The vector store that holds the capability vectors."""
        return self._store

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        """Return at most `limit` of `candidates`, most similar to `query` first.

        Raises:
            ConfigurationError: If `limit` is not a positive integer.
        """
        validate_limit(limit)
        if not candidates:
            return []
        await self._index(candidates)
        by_id = {capability.capability_id: capability for capability in candidates}
        k = max(limit, self._fetch_k) if self._reranker is not None else limit
        documents = await self._search(query, by_id, k)
        if self._reranker is not None:
            documents = await self._reranker.acompress_documents(documents, query)
        ranked = (by_id.get(_capability_id(document)) for document in documents)
        return [capability for capability in ranked if capability is not None][:limit]

    async def _search(self, query: str, by_id: dict[str, Capability], k: int) -> Sequence[Document]:
        k = min(k, len(by_id))
        if isinstance(self._store, InMemoryVectorStore):
            return await self._store.asimilarity_search(
                query, k=k, filter=lambda document: document.id in by_id
            )
        # Vector stores filter by metadata in store-specific ways, so the search
        # oversamples and keeps the candidates, widening until enough are found or
        # the store has no more documents.
        fetch = min(max(k * 4, k + 16), len(self._texts))
        while True:
            documents = await self._store.asimilarity_search(query, k=fetch)
            matches = [doc for doc in documents if _capability_id(doc) in by_id]
            if len(matches) >= k or len(documents) < fetch or fetch >= len(self._texts):
                return matches[:k]
            fetch = min(fetch * 4, len(self._texts))

    async def _index(self, candidates: Sequence[Capability]) -> None:
        async with self._lock:
            self._queries += 1
            texts = {
                capability.capability_id: _document_text(capability) for capability in candidates
            }
            await self._recover([key for key in texts if key not in self._texts])
            changed = {key: text for key, text in texts.items() if self._texts.get(key) != text}
            if changed:
                await self._store.aadd_documents(
                    [
                        Document(
                            id=capability_id,
                            page_content=text,
                            metadata={"capability_id": capability_id},
                        )
                        for capability_id, text in changed.items()
                    ],
                    ids=list(changed),
                )
                self._texts.update(changed)
            # Only stored capabilities are tracked, so a failed embedding call
            # leaves the retriever as it was.
            for capability_id in texts:
                self._seen[capability_id] = self._queries
            overflow = len(self._texts) - self._max_documents
            if overflow > 0:
                idle = [key for key, seen in self._seen.items() if seen < self._queries]
                stale = heapq.nsmallest(overflow, idle, key=self._seen.__getitem__)
                if stale:
                    await self._store.adelete(stale)
                for capability_id in stale:
                    del self._texts[capability_id]
                    del self._seen[capability_id]

    async def _recover(self, capability_ids: list[str]) -> None:
        """Learn the texts of capabilities that a persistent store already holds."""
        if not capability_ids or isinstance(self._store, InMemoryVectorStore):
            return
        try:
            documents = await self._store.aget_by_ids(capability_ids)
        except NotImplementedError:
            return
        for document in documents:
            capability_id = _capability_id(document)
            if capability_id in capability_ids:
                self._texts[capability_id] = document.page_content
                self._seen.setdefault(capability_id, 0)


def _capability_id(document: Document) -> str:
    return str(document.metadata.get("capability_id") or document.id or "")


class HybridRetriever(CapabilityRetriever):
    """Fuses the rankings of several retrievers with reciprocal rank fusion.

    Each retriever ranks the same candidates concurrently; a capability scores
    `weight / (k + rank)` in each ranking that contains it, and the capabilities
    with the highest total score win. Combining a `KeywordRetriever`, which finds
    exact names, with an `EmbeddingRetriever`, which finds paraphrases, usually
    beats either alone. Ties are broken by capability ID.

    Example:
        ```python
        retriever = HybridRetriever(
            [KeywordRetriever(), EmbeddingRetriever(embeddings)], weights=[1.0, 2.0]
        )
        ```
    """

    def __init__(
        self,
        retrievers: Iterable[CapabilityRetriever],
        *,
        weights: Iterable[float] | None = None,
        k: int = 60,
        fetch_k: int = 50,
    ) -> None:
        """Create a retriever.

        Args:
            retrievers: The retrievers to fuse; at least one.
            weights: The weight of each retriever's ranking; 1 for every retriever
                when `None`.
            k: The rank constant of the fusion; larger values flatten the
                difference between top and lower ranks.
            fetch_k: How many matches to take from each retriever; at least the
                requested limit.

        Raises:
            ConfigurationError: If an argument is invalid.
        """
        self._retrievers = tuple(retrievers)
        if not self._retrievers:
            msg = "HybridRetriever needs at least one retriever"
            raise ConfigurationError(msg)
        for retriever in self._retrievers:
            if not isinstance(retriever, CapabilityRetriever):
                msg = f"retriever {retriever!r} does not subclass CapabilityRetriever"
                raise ConfigurationError(msg)
        self._weights = (
            tuple(float(weight) for weight in weights)
            if weights is not None
            else (1.0,) * len(self._retrievers)
        )
        if len(self._weights) != len(self._retrievers):
            msg = f"got {len(self._weights)} weights for {len(self._retrievers)} retrievers"
            raise ConfigurationError(msg)
        if any(not math.isfinite(weight) or weight < 0 for weight in self._weights):
            msg = f"weights must be finite and non-negative, got {self._weights!r}"
            raise ConfigurationError(msg)
        self._k = _positive("k", k)
        self._fetch_k = _positive("fetch_k", fetch_k)

    @property
    def retrievers(self) -> tuple[CapabilityRetriever, ...]:
        """The fused retrievers."""
        return self._retrievers

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        """Return at most `limit` of `candidates`, best fused rank first.

        Raises:
            ConfigurationError: If `limit` is not a positive integer.
        """
        validate_limit(limit)
        if not candidates:
            return []
        fetch = max(limit, self._fetch_k)
        rankings: list[list[Capability]] = await gather_or_cancel(
            *(retriever.retrieve(query, candidates, limit=fetch) for retriever in self._retrievers)
        )
        scores: dict[str, float] = {}
        by_id: dict[str, Capability] = {}
        for ranking, weight in zip(rankings, self._weights, strict=True):
            for rank, capability in enumerate(ranking, start=1):
                key = capability.capability_id
                by_id[key] = capability
                scores[key] = scores.get(key, 0.0) + weight / (self._k + rank)
        best = heapq.nsmallest(limit, scores, key=lambda key: (-scores[key], key))
        return [by_id[key] for key in best]
