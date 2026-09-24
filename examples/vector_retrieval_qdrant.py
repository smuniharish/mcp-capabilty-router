"""Pluggable vector retrieval backed by a real Qdrant instance.

This demonstrates the architecture claim that retrieval is a pluggable concern -- the
core package ships a deterministic, dependency-free ``DeterministicRetriever``, but an
application can drop in a vector-backed ``CapabilityRetriever`` implementation without
changing anything else in ``MCPRuntime``.

Run a real Qdrant instance with Podman first:

    podman run -d --name mcp-router-qdrant -p 6333:6333 -p 6334:6334 qdrant/qdrant:latest

Then run this example (set ``QDRANT_URL`` if Qdrant is not reachable at the default
``http://localhost:6333``, for example when a container runtime's port publishing is not
forwarded to the host and the VM's own address must be used instead):

    uv run python -m examples.vector_retrieval_qdrant

Prerequisites:
    ``uv sync --extra examples`` (installs ``qdrant-client``) and a reachable Qdrant
    instance.

Embeddings: to keep this example runnable without downloading an embedding model or
calling a hosted embeddings API, capability text is embedded with a small deterministic
hashing-trick vectorizer (``_embed``). Swap it for a real LangChain ``Embeddings``
implementation (``OpenAIEmbeddings``, ``HuggingFaceEmbeddings``, etc.) in a production
application; the ``QdrantCapabilityRetriever`` boundary does not change.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable, Sequence

from qdrant_client import AsyncQdrantClient, models

from mcp_capability_router import CapabilityType, MCPRuntime
from mcp_capability_router.embedding import CapabilityEmbedder
from mcp_capability_router.models import Capability
from mcp_capability_router.retrieval import CapabilityRetrieverBase

_VECTOR_SIZE = 64
_COLLECTION = "mcp_capabilities"

EmbedFn = Callable[[str], Awaitable[list[float]]]


def _embed(text: str) -> list[float]:
    """Deterministic bag-of-words hashing-trick embedding (no model download required)."""
    vector = [0.0] * _VECTOR_SIZE
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % _VECTOR_SIZE
        vector[index] += 1.0
    norm = sum(component * component for component in vector) ** 0.5
    if norm:
        vector = [component / norm for component in vector]
    return vector


class HashingTrickEmbedder(CapabilityEmbedder):
    """Default, dependency-free ``CapabilityEmbedder``: a deterministic hashing-trick
    vectorizer. Swap this for a real ``CapabilityEmbedder`` (see
    ``examples/embedding_ollama.py``'s ``OllamaEmbedder``) in a production application; the
    ``QdrantCapabilityRetriever`` boundary does not change either way.
    """

    async def embed(self, text: str) -> list[float]:
        return _embed(text)


_default_embedder = HashingTrickEmbedder()


def _stable_point_id(capability_id: str) -> int:
    """A stable point id derived from ``capability_id``.

    Python's builtin ``hash()`` is salted per-process (``PYTHONHASHSEED``), so using it
    here would mint a *different* Qdrant point id for the same capability on every run,
    leaving stale duplicate vectors behind instead of upserting into the same point. A
    deterministic SHA-256-based id keeps re-runs idempotent.
    """
    digest = hashlib.sha256(capability_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % (2**63)


class QdrantCapabilityRetriever(CapabilityRetrieverBase):
    """A ``CapabilityRetriever`` backed by a real Qdrant collection.

    Subclasses ``CapabilityRetrieverBase`` to prove the retriever base class is a drop-in
    template for a real, non-trivial implementation; nothing in ``MCPRuntime`` needs to know
    a vector database is involved. ``sync(candidates)`` upserts the current registry
    snapshot into Qdrant so the vector index stays reconciled with capability metadata
    (mirroring how the runtime already reconciles its in-memory registry on refresh).

    The embedding function is itself injected (``embed_fn``), independently of the vector
    backend -- see ``examples/embedding_ollama.py``, which reuses this exact class with a
    real Ollama-backed ``embed_fn`` instead of the default deterministic hashing-trick one,
    proving the embedding model is a second, independently swappable plugin point.
    """

    def __init__(
        self,
        client: AsyncQdrantClient,
        *,
        collection: str = _COLLECTION,
        vector_size: int = _VECTOR_SIZE,
        embed_fn: EmbedFn = _default_embedder,
    ) -> None:
        self.client = client
        self.collection = collection
        self.vector_size = vector_size
        self.embed_fn = embed_fn

    async def ensure_collection(self) -> None:
        exists = await self.client.collection_exists(self.collection)
        if not exists:
            await self.client.create_collection(
                self.collection,
                vectors_config=models.VectorParams(
                    size=self.vector_size, distance=models.Distance.COSINE
                ),
            )

    async def sync(self, candidates: Sequence[Capability]) -> None:
        """Reconcile the vector index with the current capability metadata."""
        await self.ensure_collection()
        points = [
            models.PointStruct(
                id=_stable_point_id(capability.capability_id),
                vector=await self.embed_fn(f"{capability.name} {capability.description or ''}"),
                payload={"capability_id": capability.capability_id},
            )
            for capability in candidates
        ]
        if points:
            await self.client.upsert(self.collection, points=points)

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int = 20
    ) -> list[Capability]:
        await self.sync(candidates)
        by_id = {capability.capability_id: capability for capability in candidates}
        hits = await self.client.query_points(
            self.collection, query=await self.embed_fn(query), limit=limit
        )
        ordered = [
            by_id[point.payload["capability_id"]]
            for point in hits.points
            if point.payload and point.payload.get("capability_id") in by_id
        ]
        return ordered


class DirectoryAdapter:
    """Small in-process adapter exposing a mix of tools, resources, and prompts."""

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [
            {"name": "search_orders", "description": "search customer orders by status"},
            {"name": "issue_refund", "description": "issue a refund for a completed order"},
        ]

    async def list_resources(self):
        return [
            {
                "uri": "file:///refund-policy.md",
                "name": "refund_policy",
                "description": "refund policy reference document",
            }
        ]

    async def list_prompts(self):
        return [
            {
                "name": "explain_refund",
                "description": "explain a refund decision to a customer",
                "arguments": [{"name": "order_id"}],
            }
        ]

    async def call_tool(self, name, arguments=None):
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        return "Refunds are issued within 5 business days of approval."

    async def get_prompt(self, name, arguments=None):
        return {"instructions": f"Explain the refund for order {(arguments or {}).get('order_id')}"}


async def main() -> None:
    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    client = AsyncQdrantClient(url=qdrant_url)
    retriever = QdrantCapabilityRetriever(client)

    async with MCPRuntime(retriever=retriever) as runtime:
        await runtime.register_server("commerce", lambda: DirectoryAdapter())
        await runtime.refresh_server("commerce")

        tools = await runtime.retrieve("refund a customer order", type=CapabilityType.TOOL)
        print("vector-ranked tools:", [tool.name for tool in tools])

        resources = await runtime.retrieve("refund policy", type=CapabilityType.RESOURCE)
        print("vector-ranked resources:", [resource.name for resource in resources])

        if tools:
            print("executed:", await runtime.execute(tools[0].capability_id, {"status": "open"}))

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
