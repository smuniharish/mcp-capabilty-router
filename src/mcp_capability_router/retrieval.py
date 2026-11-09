"""Capability retrieval: the default Qdrant retriever and the embedder contract."""

from __future__ import annotations

import asyncio
import hashlib
import heapq
import math
import re
import uuid
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Literal

from ._internal.naming import validate_limit, validate_positive
from .contracts import CapabilityRetriever
from .errors import ConfigurationError
from .models import Capability, Resource

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from qdrant_client import AsyncQdrantClient

type RetrievalMode = Literal["hybrid", "dense", "sparse"]
"""How `QdrantRetriever` ranks: sparse BM25, dense embeddings, or both fused."""

type Fusion = Literal["rrf", "dbsf"]
"""How hybrid rankings are fused: reciprocal rank fusion or distribution-based
score fusion."""

_DENSE = "dense"
_SPARSE = "sparse"
_POINT_NAMESPACE = uuid.UUID("6f1f6b0e-3c7a-5e0c-9a54-2d8e8f2f7c11")
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
_STEM_LENGTH = 5
_STEM_SHARE = 0.5


class Embedder(ABC):
    """Turns text into dense vectors for `QdrantRetriever`.

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
    """Yield the sparse terms of `text` with the share of a match each carries.

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


def _term_index(term: str) -> int:
    return int.from_bytes(hashlib.blake2b(term.encode(), digest_size=4).digest(), "big")


def _fields(capability: Capability) -> tuple[tuple[float, str], ...]:
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


def _point_id(capability_id: str) -> str:
    return str(uuid.uuid5(_POINT_NAMESPACE, capability_id))


def _is_local(client: AsyncQdrantClient) -> bool:
    """Whether `client` runs Qdrant in process, where payload indexes do nothing."""
    options = client.init_options
    return options.get("location") == ":memory:" or options.get("path") is not None


def _number(name: str, value: object, *, low: float, high: float, positive: bool = False) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or not low <= value <= high
        or (positive and value <= 0)
    ):
        msg = f"{name} is out of range: {value!r}"
        raise ConfigurationError(msg)
    return float(value)


class QdrantRetriever(CapabilityRetriever):
    """Ranks capabilities with Qdrant: sparse BM25, dense embeddings, or both.

    The default retriever of `MCPRuntime`. Without arguments it keeps an
    in-process Qdrant collection, needs no model and no service, and ranks
    with BM25. Give it an `Embedder` to rank by meaning as well: the sparse and
    dense rankings are fused by Qdrant, with reciprocal rank fusion by default.
    Give it an `AsyncQdrantClient` to keep the collection in a Qdrant server,
    shared between processes and kept across restarts.

    BM25 works on words: identifiers such as `read_text_file` or `getWeather`
    are split into words, plurals match their singular, and words that share
    their first five letters match partly. A word in the name or title weighs
    3, in a tag 2, and in the description or resource URI 1. Qdrant weighs each
    word by its inverse document frequency, so rare words count more than words
    that most capabilities share.

    Capabilities are indexed on first sight and re-indexed only when their text
    changes; with an external collection, capabilities that it already holds
    are not embedded again. Each query searches only the candidates it is
    given.

    Example:
        ```python
        from qdrant_client import AsyncQdrantClient

        retriever = QdrantRetriever(
            embedder=my_embedder,
            client=AsyncQdrantClient(url="http://localhost:6333"),
            fusion="dbsf",
        )
        runtime = MCPRuntime(retriever=retriever)
        ```
    """

    def __init__(
        self,
        *,
        embedder: Embedder | None = None,
        mode: RetrievalMode | None = None,
        client: AsyncQdrantClient | None = None,
        collection_name: str = "mcp_capabilities",
        fusion: Fusion = "rrf",
        rrf_k: int | None = None,
        prefetch_limit: int = 50,
        k1: float = 1.2,
        b: float = 0.75,
        avg_length: float = 24.0,
        max_points: int = 50_000,
    ) -> None:
        """Create a retriever.

        Args:
            embedder: Embeds capabilities and queries for dense ranking.
            mode: `"sparse"` ranks with BM25 only, `"dense"` with the embedder
                only, and `"hybrid"` fuses both. `"hybrid"` when an embedder is
                given, `"sparse"` otherwise.
            client: The Qdrant client that holds the collection; an in-process
                `AsyncQdrantClient(":memory:")` when `None`. The retriever closes
                only a client it created.
            collection_name: The collection that holds the capability points.
                Give each runtime that indexes a different catalog its own
                collection.
            fusion: How hybrid rankings are fused: `"rrf"`, reciprocal rank
                fusion, or `"dbsf"`, distribution-based score fusion.
            rrf_k: The `k` constant of reciprocal rank fusion; Qdrant's default
                when `None`.
            prefetch_limit: How many matches each ranking contributes to hybrid
                fusion; at least the requested limit.
            k1: The BM25 term-frequency saturation.
            b: The BM25 length normalization, from 0 to 1.
            avg_length: The average weighted length of a capability text, used
                by BM25 length normalization.
            max_points: Number of capabilities to keep indexed. When exceeded,
                the capabilities seen least recently are dropped; the candidates
                of the current query are always kept.

        Raises:
            ConfigurationError: If an argument is invalid, or `mode` needs an
                embedder that is not given.
        """
        if embedder is not None and not isinstance(embedder, Embedder):
            msg = f"embedder {embedder!r} does not subclass Embedder"
            raise ConfigurationError(msg)
        if mode is None:
            mode = "hybrid" if embedder is not None else "sparse"
        if mode not in ("hybrid", "dense", "sparse"):
            msg = f"mode must be 'hybrid', 'dense', or 'sparse', got {mode!r}"
            raise ConfigurationError(msg)
        if mode == "sparse" and embedder is not None:
            msg = "the sparse mode does not use an embedder; use 'hybrid' or 'dense'"
            raise ConfigurationError(msg)
        if mode != "sparse" and embedder is None:
            msg = f"the {mode} mode needs an embedder"
            raise ConfigurationError(msg)
        if client is not None:
            from qdrant_client import AsyncQdrantClient

            if not isinstance(client, AsyncQdrantClient):
                msg = f"client {client!r} is not a qdrant_client.AsyncQdrantClient"
                raise ConfigurationError(msg)
        if not isinstance(collection_name, str) or not collection_name:
            msg = f"collection_name must be a non-empty string, got {collection_name!r}"
            raise ConfigurationError(msg)
        if fusion not in ("rrf", "dbsf"):
            msg = f"fusion must be 'rrf' or 'dbsf', got {fusion!r}"
            raise ConfigurationError(msg)
        if rrf_k is not None:
            validate_positive("rrf_k", rrf_k)
            if fusion != "rrf":
                msg = "rrf_k applies only to the 'rrf' fusion"
                raise ConfigurationError(msg)
        self._embedder = embedder
        self._mode: RetrievalMode = mode
        self._client = client
        self._owns_client = client is None
        self._collection = collection_name
        self._fusion: Fusion = fusion
        self._rrf_k = rrf_k
        self._prefetch_limit = validate_positive("prefetch_limit", prefetch_limit)
        self._k1 = _number("k1", k1, low=0.0, high=math.inf)
        self._b = _number("b", b, low=0.0, high=1.0)
        self._avg_length = _number("avg_length", avg_length, low=0.0, high=math.inf, positive=True)
        self._max_points = validate_positive("max_points", max_points)
        self._ready = False
        self._dense_size: int | None = None
        self._digests: dict[str, str] = {}
        self._seen: dict[str, int] = {}
        self._queries = 0
        self._lock = asyncio.Lock()

    @property
    def mode(self) -> RetrievalMode:
        """How the retriever ranks: `"hybrid"`, `"dense"`, or `"sparse"`."""
        return self._mode

    @property
    def collection_name(self) -> str:
        """The collection that holds the capability points."""
        return self._collection

    @property
    def client(self) -> AsyncQdrantClient:
        """The Qdrant client that holds the collection."""
        if self._client is None:
            from qdrant_client import AsyncQdrantClient

            self._client = AsyncQdrantClient(":memory:")
        return self._client

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        """Return at most `limit` of `candidates` that match `query`, best first.

        Equal scores are ordered by capability ID, so rankings do not depend on
        the order in which capabilities were indexed. A query without usable
        words returns the candidates in capability-ID order in the sparse mode.

        Raises:
            ConfigurationError: If `limit` is not a positive integer, or the
                collection or the embeddings do not fit the retriever.
        """
        from qdrant_client import models

        validate_limit(limit)
        if not candidates:
            return []
        await self._index(candidates)
        by_id = {capability.capability_id: capability for capability in candidates}
        sparse = self._query_vector(query)
        if self._mode == "sparse" and sparse is None:
            return heapq.nsmallest(limit, by_id.values(), key=lambda c: c.capability_id)
        query_filter = None
        if not (self._owns_client and len(by_id) == len(self._digests)):
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="capability_id", match=models.MatchAny(any=list(by_id))
                    )
                ]
            )
        options: dict[str, Any] = {
            "query_filter": query_filter,
            "with_payload": ["capability_id"],
        }
        if self._mode == "sparse":
            options |= {"query": sparse, "using": _SPARSE}
        else:
            embedder = self._embedder
            assert embedder is not None  # noqa: S101 - guaranteed by the mode
            dense = [float(value) for value in await embedder.embed_query(query)]
            if self._mode == "dense" or sparse is None:
                options |= {"query": dense, "using": _DENSE}
            else:
                width = max(self._prefetch_limit, limit)
                options |= {
                    "prefetch": [
                        models.Prefetch(query=dense, using=_DENSE, limit=width),
                        models.Prefetch(query=sparse, using=_SPARSE, limit=width),
                    ],
                    "query": self._fusion_query(),
                }
        response = await self.client.query_points(
            self._collection, **(options | {"limit": min(limit + 1, len(by_id))})
        )
        points = response.points
        if len(points) > limit and points[limit].score == points[limit - 1].score:
            # Points that tie at the cut are returned in insertion order, so
            # fetch every point that scores about as high and break the tie by
            # capability ID. The margin covers local Qdrant, which compares
            # float32 scores strictly.
            score = points[limit].score
            threshold = score - max(abs(score), 1.0) * 1e-6
            tied = await self.client.query_points(
                self._collection,
                **(options | {"limit": len(by_id), "score_threshold": threshold}),
            )
            points = tied.points
        ranked = [
            (point.score, key)
            for point in points
            if (key := str((point.payload or {}).get("capability_id"))) in by_id
        ]
        ranked.sort(key=lambda item: (-item[0], item[1]))
        return [by_id[key] for _, key in ranked[:limit]]

    async def close(self) -> None:
        """Close the Qdrant client if the retriever created it."""
        if not self._owns_client or self._client is None:
            return
        client, self._client = self._client, None
        self._ready = False
        self._dense_size = None
        self._digests.clear()
        self._seen.clear()
        await client.close()

    def _fusion_query(self) -> Any:
        from qdrant_client import models

        if self._fusion == "dbsf":
            return models.FusionQuery(fusion=models.Fusion.DBSF)
        if self._rrf_k is not None:
            return models.RrfQuery(rrf=models.Rrf(k=self._rrf_k))
        return models.FusionQuery(fusion=models.Fusion.RRF)

    def _query_vector(self, query: str) -> Any:
        from qdrant_client import models

        values: dict[int, float] = {}
        for term, share in _terms(query):
            index = _term_index(term)
            values[index] = max(values.get(index, 0.0), share)
        if not values:
            return None
        return models.SparseVector(indices=list(values), values=list(values.values()))

    def _document_vector(self, capability: Capability) -> Any:
        from qdrant_client import models

        frequencies: dict[int, float] = {}
        for weight, text in _fields(capability):
            for term, share in _terms(text):
                index = _term_index(term)
                frequencies[index] = frequencies.get(index, 0.0) + weight * share
        length = sum(frequencies.values())
        norm = self._k1 * (1 - self._b + self._b * length / self._avg_length)
        return models.SparseVector(
            indices=list(frequencies),
            values=[tf * (self._k1 + 1) / (tf + norm) for tf in frequencies.values()],
        )

    def _digest(self, text: str) -> str:
        fingerprint = f"{self._k1}|{self._b}|{self._avg_length}|{self._mode}\n{text}"
        return hashlib.sha256(fingerprint.encode()).hexdigest()

    async def _index(self, candidates: Sequence[Capability]) -> None:
        from qdrant_client import models

        async with self._lock:
            self._queries += 1
            by_id = {capability.capability_id: capability for capability in candidates}
            texts = {key: document_text(capability) for key, capability in by_id.items()}
            digests = {key: self._digest(text) for key, text in texts.items()}
            await self._open(None)
            unknown = [key for key in texts if key not in self._digests]
            if unknown and self._ready and not self._owns_client:
                await self._recover(unknown)
            changed = [key for key in texts if self._digests.get(key) != digests[key]]
            if changed:
                dense = await self._embed([texts[key] for key in changed])
                await self._open(len(dense[0]) if dense else None)
                points = []
                for position, key in enumerate(changed):
                    vector: dict[str, Any] = {_SPARSE: self._document_vector(by_id[key])}
                    if dense is not None:
                        vector[_DENSE] = dense[position]
                    points.append(
                        models.PointStruct(
                            id=_point_id(key),
                            vector=vector,
                            payload={"capability_id": key, "digest": digests[key]},
                        )
                    )
                await self.client.upsert(self._collection, points=points)
                self._digests.update((key, digests[key]) for key in changed)
            for key in texts:
                self._seen[key] = self._queries
            await self._evict()

    async def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if self._mode == "sparse":
            return None
        embedder = self._embedder
        assert embedder is not None  # noqa: S101 - guaranteed by the mode
        vectors = [
            [float(value) for value in vector] for vector in await embedder.embed_documents(texts)
        ]
        size = self._dense_size or (len(vectors[0]) if vectors else 0)
        if len(vectors) != len(texts) or not size or any(len(v) != size for v in vectors):
            msg = (
                f"the embedder returned {len(vectors)} vectors for {len(texts)} texts, "
                f"or vectors whose size is not {size}"
            )
            raise ConfigurationError(msg)
        return vectors

    async def _open(self, dense_size: int | None) -> None:
        """Validate or create the collection once the dense size is known."""
        from qdrant_client import models

        if self._ready:
            return
        client = self.client
        if await client.collection_exists(self._collection):
            info = await client.get_collection(self._collection)
            self._validate(info.config.params.vectors, info.config.params.sparse_vectors)
            self._ready = True
            return
        if self._mode != "sparse" and dense_size is None:
            return
        await client.create_collection(
            self._collection,
            vectors_config=(
                {_DENSE: models.VectorParams(size=dense_size, distance=models.Distance.COSINE)}
                if dense_size is not None
                else {}
            ),
            sparse_vectors_config={
                _SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )
        if not self._owns_client and not _is_local(client):
            await client.create_payload_index(
                self._collection, "capability_id", models.PayloadSchemaType.KEYWORD
            )
        self._dense_size = dense_size
        self._ready = True

    def _validate(self, vectors: Any, sparse_vectors: Any) -> None:
        from qdrant_client import models

        sparse = (sparse_vectors or {}).get(_SPARSE)
        if sparse is None or sparse.modifier != models.Modifier.IDF:
            msg = (
                f"collection {self._collection!r} has no sparse vector {_SPARSE!r} "
                "with the IDF modifier; give the retriever a collection of its own"
            )
            raise ConfigurationError(msg)
        if self._mode == "sparse":
            return
        dense = vectors.get(_DENSE) if isinstance(vectors, dict) else None
        if dense is None:
            msg = (
                f"collection {self._collection!r} has no dense vector {_DENSE!r}; "
                "give the retriever a collection of its own"
            )
            raise ConfigurationError(msg)
        self._dense_size = dense.size

    async def _recover(self, capability_ids: list[str]) -> None:
        """Learn which capabilities an external collection already holds."""
        records = await self.client.retrieve(
            self._collection,
            ids=[_point_id(key) for key in capability_ids],
            with_payload=["capability_id", "digest"],
        )
        for record in records:
            payload = record.payload or {}
            key, digest = payload.get("capability_id"), payload.get("digest")
            if isinstance(key, str) and isinstance(digest, str):
                self._digests[key] = digest
                self._seen.setdefault(key, 0)

    async def _evict(self) -> None:
        from qdrant_client import models

        overflow = len(self._digests) - self._max_points
        if overflow <= 0:
            return
        idle = [key for key, seen in self._seen.items() if seen < self._queries]
        stale = heapq.nsmallest(overflow, idle, key=self._seen.__getitem__)
        if not stale:
            return
        await self.client.delete(
            self._collection,
            points_selector=models.PointIdsList(points=[_point_id(key) for key in stale]),
        )
        for key in stale:
            del self._digests[key]
            del self._seen[key]
