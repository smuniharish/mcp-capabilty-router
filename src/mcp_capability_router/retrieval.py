"""Capability retrieval: the default RetrievalLoom retriever and the embedder contract."""

from __future__ import annotations

import asyncio
import dataclasses
import functools
import hashlib
import heapq
import re
from abc import ABC, abstractmethod
from collections import Counter
from typing import TYPE_CHECKING

import pydantic
import retrievalloom
from retrievalloom import (
    ChannelsConfig,
    Components,
    DocumentInput,
    EngineConfig,
    EngineResources,
    FusionConfig,
    FuzzyConfig,
    In,
    IndexChannelConfig,
    MethodConfig,
    Not,
    RerankingConfig,
    RetrievalConfig,
    RetrievalEngine,
    Scope,
    SourceDescriptor,
    TextRepresentation,
)
from retrievalloom.contracts.component import ComponentInfo, make_info
from retrievalloom.contracts.models import EmbeddingModelABC, RerankerABC, TokenizerABC
from retrievalloom.domain.reports import IngestOutcome

from ._internal.naming import validate_limit, validate_positive
from .contracts import CapabilityRetriever
from .errors import ConfigurationError
from .models import Capability, Resource

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from retrievalloom import FilterExpression

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
_NAME_WEIGHT = 3
_TAG_WEIGHT = 2
_TEXT_WEIGHT = 1
_STEM_LENGTH = 5
_STEM_SHARE = 0.5
_INDEXED = frozenset(
    {
        IngestOutcome.CREATED,
        IngestOutcome.UPDATED,
        IngestOutcome.UNCHANGED,
        IngestOutcome.REVIVED,
        IngestOutcome.REPLAYED,
    }
)
_CONFIGURATION_ERRORS = (
    retrievalloom.ConfigurationError,
    retrievalloom.ComponentContractError,
    retrievalloom.EmbeddingValidationError,
    retrievalloom.ValidationError,
    pydantic.ValidationError,
)


class Embedder(ABC):
    """Turns text into dense vectors for `LoomRetriever`.

    Implement it for any embedding model or service.
    `mcp_capability_router.integrations.langchain.LangChainEmbedder` adapts every
    LangChain `Embeddings`, for example `OpenAIEmbeddings`.

    Example:
        ```python
        class MyEmbedder(Embedder):
            async def embed_documents(self, texts):
                return await my_service.embed(list(texts))

            async def embed_query(self, text):
                [vector] = await my_service.embed([text])
                return vector
        ```
    """

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Return one vector per text, in the order of `texts`."""

    @abstractmethod
    async def embed_query(self, text: str) -> Sequence[float]:
        """Return the vector of a search query."""


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


def _terms(text: str) -> Iterator[tuple[str, float]]:
    """Yield the keyword terms of `text` with the share of a match each carries.

    Every word that is not a stop word is a term, with a trailing plural `s`
    dropped. A word longer than five characters also yields its five-character
    stem at half weight, so `navigation` partly matches `navigate`.
    """
    for word in _words(text):
        if word in _STOP_WORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        yield word, 1.0
        if len(word) > _STEM_LENGTH:
            yield f"~{word[:_STEM_LENGTH]}", _STEM_SHARE


def _fields(capability: Capability) -> tuple[tuple[int, str], ...]:
    return (
        (_NAME_WEIGHT, f"{capability.name} {capability.title or ''}"),
        (_TAG_WEIGHT, " ".join(sorted(capability.tags))),
        (
            _TEXT_WEIGHT,
            f"{capability.description} "
            f"{capability.uri if isinstance(capability, Resource) else ''}",
        ),
    )


def document_text(capability: Capability) -> str:
    """Return the text that represents `capability` to an embedding model."""
    name = " ".join(_words(capability.name)) or capability.name
    lines = [f"{capability.title or name} ({capability.type}: {capability.name})"]
    if capability.description:
        lines.append(capability.description)
    if capability.tags:
        lines.append("Tags: " + ", ".join(sorted(capability.tags)))
    if isinstance(capability, Resource):
        lines.append(f"URI: {capability.uri}")
    return "\n".join(lines)


@functools.lru_cache(maxsize=65_536)
def _document_id(capability_id: str) -> str:
    """Return the RetrievalLoom document ID of a capability.

    Capability IDs can hold resource URIs of any length, and document IDs are
    limited to 256 characters, so the ID is a digest of the capability ID.
    """
    return hashlib.sha256(capability_id.encode()).hexdigest()


def _query_tokens(text: str) -> list[str]:
    return list(dict.fromkeys(term for term, _ in _terms(text)))


def _document_tokens(capability: Capability) -> list[str]:
    tokens: list[str] = []
    for weight, text in _fields(capability):
        for term, share in _terms(text):
            tokens.extend([term] * round(2 * weight * share))
    return tokens


class _CapabilityTokenizer(TokenizerABC):
    """Tokenizes capability texts for keyword ranking, weighting fields by repetition.

    The engine tokenizes documents and queries with the same call, so the
    retriever registers the tokens of every document text it indexes; any other
    text is a query. BM25 counts each query term once, so query tokens are
    unique, while document tokens repeat by the weight of the field they come
    from.
    """

    def __init__(self) -> None:
        self._documents: dict[str, list[str]] = {}
        self._references: Counter[str] = Counter()
        self._info = make_info(
            component="tokenizer",
            implementation="mcp-capability-router",
            version="1",
            config={
                "name": _NAME_WEIGHT,
                "tags": _TAG_WEIGHT,
                "text": _TEXT_WEIGHT,
                "stem": _STEM_LENGTH,
            },
        )

    @property
    def info(self) -> ComponentInfo:
        """Component identity."""
        return self._info

    def add(self, text: str, capability: Capability) -> None:
        self._documents.setdefault(text, _document_tokens(capability))
        self._references[text] += 1

    def discard(self, text: str) -> None:
        self._references[text] -= 1
        if self._references[text] <= 0:
            del self._references[text]
            del self._documents[text]

    async def tokenize(self, texts: Sequence[str]) -> Sequence[Sequence[str]]:
        """Return the weighted tokens of documents and the unique tokens of queries."""
        return [self._documents.get(text) or _query_tokens(text) for text in texts]


def _default_config(*, embeds: bool, reranks: bool) -> EngineConfig:
    """Return the engine configuration of a retriever given no `config`.

    Keyword ranking is BM25 alone: fuzzy matching and keyword dictionaries
    would rank raw text and ignore the field weights. A ranking of BM25 alone
    keeps its scores, so equal scores stay equal and are ordered by capability
    ID; BM25 and embeddings are fused by reciprocal rank fusion.
    """
    return EngineConfig(
        retrieval=RetrievalConfig(
            channels=ChannelsConfig(
                index=IndexChannelConfig(
                    keyword=MethodConfig(enabled=False), fuzzy=FuzzyConfig(enabled=False)
                )
            ),
            method_fusion=FusionConfig(method="rrf" if embeds else "weighted_score"),
            channel_fusion=FusionConfig(method="weighted_score"),
            reranking=RerankingConfig(enabled=reranks),
        )
    )


class _EmbeddingModel(EmbeddingModelABC):
    """Adapts an `Embedder` to the RetrievalLoom embedding contract."""

    def __init__(self, embedder: Embedder, dimensions: int) -> None:
        self._embedder = embedder
        self._dimensions = dimensions
        kind = type(embedder)
        self._info = make_info(
            component="embedding",
            implementation=kind.__qualname__,
            version="1",
            model_identity=f"{kind.__module__}.{kind.__qualname__}",
            dimensions=dimensions,
        )

    @property
    def info(self) -> ComponentInfo:
        """Component identity."""
        return self._info

    @property
    def dimensions(self) -> int:
        """Embedding dimensionality."""
        return self._dimensions

    async def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Embed document texts with the wrapped embedder."""
        return await self._embedder.embed_documents(texts)

    async def embed_query(self, text: str) -> Sequence[float]:
        """Embed a query with the wrapped embedder."""
        return await self._embedder.embed_query(text)


class LoomRetriever(CapabilityRetriever):
    """Ranks capabilities with a RetrievalLoom engine.

    The default retriever of `MCPRuntime`. Without arguments it keeps an
    in-memory engine, needs no model and no service, and ranks with BM25. Give
    it an `Embedder` to rank by meaning as well: BM25 and the embeddings are
    fused by reciprocal rank fusion. Give it a RetrievalLoom reranker to reorder
    the fused matches with a cross-encoder. Give it RetrievalLoom `Components`,
    for example a Qdrant vector store, to keep the index in a service shared
    between processes, or `EngineResources` with a `data_dir` to keep it in
    files across restarts. A `config` replaces the engine
    configuration, including the ranking methods and their fusion.

    Keyword ranking works on words: identifiers such as `read_text_file` or
    `getWeather` are split into words, plurals match their singular, and closely
    related word forms match partly. Words in the name or title count most, then
    tags, then the description or resource URI, and rare words count more than
    words that most capabilities share.

    Capabilities are indexed on first sight and re-indexed only when their text
    changes; the engine skips documents it already holds unchanged, so a
    durable store is not embedded again after a restart. Each query searches
    only the candidates it is given.

    Example:
        ```python
        from retrievalloom import Components
        from retrievalloom.index.vector import QdrantVectorStore

        retriever = LoomRetriever(
            embedder=my_embedder,
            reranker=my_reranker,
            components=Components(vector_store=QdrantVectorStore(url="http://localhost:6333")),
        )
        runtime = MCPRuntime(retriever=retriever)
        ```
    """

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        reranker: RerankerABC | None = None,
        components: Components | None = None,
        config: EngineConfig | None = None,
        resources: EngineResources | None = None,
        tenant_id: str = "mcp-capability-router",
        collection: str = "capabilities",
        fetch_limit: int = 50,
        max_documents: int = 50_000,
    ) -> None:
        """Create a retriever.

        Args:
            embedder: Embeds capabilities and queries for dense ranking.
            reranker: Reorders the fused matches, for example a cross-encoder.
            components: RetrievalLoom components, such as durable stores. The
                retriever never closes components it is given.
            config: The engine configuration. When `None`, BM25 alone, fused
                with the embeddings when there are any, and reranking only with
                a reranker.
            resources: RetrievalLoom engine resources. A `data_dir` keeps the
                index in files, kept across restarts.
            tenant_id: The RetrievalLoom tenant that holds the capabilities.
            collection: The collection that holds the capabilities. Give each
                runtime that indexes a different catalog in a shared store its
                own collection.
            fetch_limit: How many matches to fetch from the engine before ties
                are broken; at least the requested limit.
            max_documents: Number of capabilities to keep indexed. When
                exceeded, the capabilities seen least recently are dropped; the
                candidates of the current query are always kept.

        Raises:
            ConfigurationError: If an argument is invalid, or a component is
                given both directly and in `components`.
        """
        if embedder is not None and not isinstance(embedder, Embedder):
            msg = f"embedder {embedder!r} does not subclass Embedder"
            raise ConfigurationError(msg)
        if reranker is not None and not isinstance(reranker, RerankerABC):
            msg = f"reranker {reranker!r} does not subclass retrievalloom RerankerABC"
            raise ConfigurationError(msg)
        if components is not None and not isinstance(components, Components):
            msg = f"components {components!r} is not a retrievalloom Components"
            raise ConfigurationError(msg)
        if config is not None and not isinstance(config, EngineConfig):
            msg = f"config {config!r} is not a retrievalloom EngineConfig"
            raise ConfigurationError(msg)
        if resources is not None and not isinstance(resources, EngineResources):
            msg = f"resources {resources!r} is not a retrievalloom EngineResources"
            raise ConfigurationError(msg)
        if components is not None:
            for name, value in (("embedder", embedder), ("reranker", reranker)):
                field = "embedding" if name == "embedder" else name
                if value is not None and getattr(components, field) is not None:
                    msg = f"give the {name} either directly or as components.{field}, not both"
                    raise ConfigurationError(msg)
        try:
            self._scope = Scope(tenant_id=tenant_id, collection=collection)
        except pydantic.ValidationError as error:
            msg = f"invalid tenant_id {tenant_id!r} or collection {collection!r}: {error}"
            raise ConfigurationError(msg) from error
        if config is None:
            config = _default_config(
                embeds=embedder is not None
                or (components is not None and components.embedding is not None),
                reranks=reranker is not None
                or (components is not None and components.reranker is not None),
            )
        self._embedder = embedder
        self._reranker = reranker
        self._components = components
        self._config = config
        self._resources = resources
        # Only an engine of its own, kept in memory, holds just what this
        # retriever indexed, so a query may skip or invert the candidate filter.
        self._private = components is None and (resources is None or resources.data_dir is None)
        self._fetch_limit = validate_positive("fetch_limit", fetch_limit)
        self._max_documents = validate_positive("max_documents", max_documents)
        self._embeds = embedder is not None or (
            components is not None and components.embedding is not None
        )
        self._engine: RetrievalEngine | None = None
        self._tokenizer = _CapabilityTokenizer()
        self._texts: dict[str, str] = {}
        self._seen: dict[str, int] = {}
        self._queries = 0
        self._lock = asyncio.Lock()

    @property
    def engine(self) -> RetrievalEngine | None:
        """The RetrievalLoom engine, created by the first query and dropped by `close`."""
        return self._engine

    @property
    def scope(self) -> Scope:
        """The RetrievalLoom scope that holds the capabilities."""
        return self._scope

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        """Return at most `limit` of `candidates` that match `query`, best first.

        Equal scores are ordered by capability ID, so rankings do not depend on
        the order in which capabilities were indexed. A blank query, or one
        without usable words when nothing embeds it, returns the candidates in
        capability-ID order.

        Raises:
            ConfigurationError: If `limit` is not a positive integer, or the
                engine rejects its configuration or components.
        """
        validate_limit(limit)
        if not candidates:
            return []
        by_id = {capability.capability_id: capability for capability in candidates}
        engine = await self._index(by_id)
        query = query[: self._config.retrieval.max_query_chars]
        if not query.strip() or (not self._embeds and not _query_tokens(query)):
            return heapq.nsmallest(limit, by_id.values(), key=lambda c: c.capability_id)
        top_k = min(
            max(limit, self._fetch_limit),
            len(by_id),
            self._config.retrieval.default_tenant_policy.max_top_k,
        )
        try:
            result = await engine.retrieve(
                query, scope=self._scope, filters=self._filter(by_id), top_k=top_k
            )
        except _CONFIGURATION_ERRORS as error:
            raise ConfigurationError(str(error)) from error
        documents = {_document_id(key): key for key in by_id}
        scores: dict[str, float] = {}
        for evidence in result.evidence:
            ids = (source.document_id for source in evidence.sources)
            for key in filter(None, map(documents.get, ids)):
                scores.setdefault(key, evidence.score)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [by_id[key] for key, _ in ranked[:limit]]

    async def close(self) -> None:
        """Close the engine; components given to the retriever stay open."""
        engine, self._engine = self._engine, None
        if engine is None:
            return
        self._tokenizer = _CapabilityTokenizer()
        self._texts.clear()
        self._seen.clear()
        await engine.close()

    def _filter(self, by_id: dict[str, Capability]) -> FilterExpression | None:
        """Restrict a query to the candidates, with the smallest filter that does."""
        if self._private:
            excluded = self._texts.keys() - by_id.keys()
            if not excluded:
                return None
            if len(excluded) < len(by_id):
                return Not(clause=In(field="_id", values=tuple(map(_document_id, excluded))))
        return In(field="_id", values=tuple(map(_document_id, by_id)))

    async def _index(self, by_id: dict[str, Capability]) -> RetrievalEngine:
        async with self._lock:
            engine = await self._start()
            self._queries += 1
            changed = [
                (key, capability, text)
                for key, capability in by_id.items()
                if self._texts.get(key) != (text := document_text(capability))
            ]
            if changed:
                await self._ingest(engine, changed)
            for key in by_id:
                if key in self._texts:
                    self._seen[key] = self._queries
            await self._evict(engine)
            return engine

    async def _start(self) -> RetrievalEngine:
        if self._engine is not None:
            return self._engine
        components = self._components or Components()
        tokenizer = self._tokenizer if components.tokenizer is None else components.tokenizer
        embedding = components.embedding
        if self._embedder is not None:
            probe = await self._embedder.embed_query("capability")
            if not probe:
                msg = "the embedder returned an empty vector"
                raise ConfigurationError(msg)
            embedding = _EmbeddingModel(self._embedder, len(probe))
        reranker = components.reranker if self._reranker is None else self._reranker
        try:
            engine = RetrievalEngine(
                self._config,
                dataclasses.replace(
                    components, tokenizer=tokenizer, embedding=embedding, reranker=reranker
                ),
                self._resources,
            )
            try:
                await engine.initialize()
            except BaseException:
                await engine.close()
                raise
        except _CONFIGURATION_ERRORS as error:
            raise ConfigurationError(str(error)) from error
        self._engine = engine
        return engine

    async def _ingest(
        self, engine: RetrievalEngine, changed: list[tuple[str, Capability, str]]
    ) -> None:
        size = self._config.ingestion.limits.max_documents_per_call
        for start in range(0, len(changed), size):
            batch = changed[start : start + size]
            for _, capability, text in batch:
                self._tokenizer.add(text, capability)
            documents = [
                DocumentInput(
                    id=_document_id(key),
                    metadata={"capability_id": key, "type": capability.type},
                    source=SourceDescriptor(
                        title=capability.title or capability.name,
                        uri=capability.uri if isinstance(capability, Resource) else None,
                    ),
                    representations=(TextRepresentation(text=text),),
                )
                for key, capability, text in batch
            ]
            try:
                report = await engine.ingest(documents, scope=self._scope)
            except _CONFIGURATION_ERRORS as error:
                for _, _, text in batch:
                    self._tokenizer.discard(text)
                raise ConfigurationError(str(error)) from error
            indexed = {
                result.document_id for result in report.documents if result.outcome in _INDEXED
            }
            for key, _, text in batch:
                if _document_id(key) not in indexed:
                    self._tokenizer.discard(text)
                    continue
                previous = self._texts.get(key)
                if previous is not None:
                    self._tokenizer.discard(previous)
                self._texts[key] = text

    async def _evict(self, engine: RetrievalEngine) -> None:
        overflow = len(self._texts) - self._max_documents
        if overflow <= 0:
            return
        idle = [key for key, seen in self._seen.items() if seen < self._queries]
        stale = heapq.nsmallest(overflow, idle, key=self._seen.__getitem__)
        if not stale:
            return
        await engine.delete([_document_id(key) for key in stale], scope=self._scope)
        for key in stale:
            self._tokenizer.discard(self._texts.pop(key))
            del self._seen[key]
