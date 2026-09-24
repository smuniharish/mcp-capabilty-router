"""Pluggable embedding model, backed by a real local Ollama instance.

This is the embedding-side counterpart to ``examples/vector_retrieval_qdrant.py``: that
example proves the *vector backend* is swappable (Qdrant instead of the in-process
deterministic retriever); this example proves the *embedding model* used to produce those
vectors is an independent, second plugin point. It reuses the exact same
``QdrantCapabilityRetriever`` class, only swapping its injected ``embed_fn`` for one that
calls a real, locally hosted Ollama embedding model instead of the deterministic
hashing-trick fallback.

Run a real Ollama instance with Podman first, then pull/create an embedding model:

    podman run -d --name mcp-router-ollama -p 11434:11434 ollama/ollama:latest

Prefer ``ollama pull <embedding-model>`` (e.g. ``nomic-embed-text``, ``all-minilm``) if
your network allows reaching ``registry.ollama.ai``. In this project's own development
sandbox that registry -- and Hugging Face's model-download endpoint -- were both blocked
by an outbound content-security policy (see ``docs/guides/agent-integrations.md`` for the
full, real finding), so the verified run instead loaded a small GGUF embedding model
(``all-MiniLM-L6-v2``, quantized) from a plain GitHub file download and registered it
with Ollama directly from the GGUF, with no Modelfile beyond ``FROM <path-to-gguf>``:

    ollama create local-minilm -f Modelfile   # Modelfile contents: FROM /path/to/model.gguf

Either way, once any embedding model is available in Ollama, run this example:

    uv sync --extra examples
    uv run python -m examples.embedding_ollama

Environment variables:
    ``OLLAMA_URL`` -- defaults to ``http://localhost:11434``.
    ``OLLAMA_EMBED_MODEL`` -- defaults to ``local-minilm``; set to whatever model name you
    pulled/created (e.g. ``nomic-embed-text``, ``all-minilm``).
    ``QDRANT_URL`` -- defaults to ``http://localhost:6333``, same as the Qdrant example.
"""

from __future__ import annotations

import asyncio
import os

import httpx
from qdrant_client import AsyncQdrantClient

from examples.vector_retrieval_qdrant import DirectoryAdapter, QdrantCapabilityRetriever
from mcp_capability_router import CapabilityType, MCPRuntime
from mcp_capability_router.embedding import CapabilityEmbedder

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "local-minilm")


class OllamaEmbedder(CapabilityEmbedder):
    """Calls a real, locally hosted Ollama model's ``/api/embed`` endpoint.

    Subclasses ``CapabilityEmbedder`` -- this is exactly the kind of application-owned
    embedding client the deterministic hashing-trick embedder in
    ``vector_retrieval_qdrant.py`` explicitly says should be swapped in for production use.
    Nothing in ``QdrantCapabilityRetriever`` or ``MCPRuntime`` needs to change to accept it;
    ``CapabilityEmbedder.__call__`` already makes it usable wherever ``embed_fn`` is expected.
    """

    def __init__(self, base_url: str, model: str) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self.model = model
        self._dim: int | None = None

    async def dimension(self) -> int:
        if self._dim is None:
            self._dim = len(await self.embed(" "))
        return self._dim

    async def embed(self, text: str) -> list[float]:
        response = await self._client.post("/api/embed", json={"model": self.model, "input": text})
        response.raise_for_status()
        return response.json()["embeddings"][0]

    async def close(self) -> None:
        await self._client.aclose()


async def main() -> None:
    embedder = OllamaEmbedder(OLLAMA_URL, OLLAMA_EMBED_MODEL)
    vector_size = await embedder.dimension()
    print(f"real Ollama embedding model {OLLAMA_EMBED_MODEL!r} reports dimension {vector_size}")

    qdrant_url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    client = AsyncQdrantClient(url=qdrant_url)
    retriever = QdrantCapabilityRetriever(
        client,
        collection="mcp_capabilities_ollama",
        vector_size=vector_size,
        embed_fn=embedder,
    )

    async with MCPRuntime(retriever=retriever) as runtime:
        await runtime.register_server("commerce", lambda: DirectoryAdapter())
        await runtime.refresh_server("commerce")

        tools = await runtime.retrieve("refund a customer order", type=CapabilityType.TOOL)
        print("Ollama-embedding-ranked tools:", [tool.name for tool in tools])

        resources = await runtime.retrieve("refund policy", type=CapabilityType.RESOURCE)
        print("Ollama-embedding-ranked resources:", [resource.name for resource in resources])

        if tools:
            print("executed:", await runtime.execute(tools[0].capability_id, {"status": "open"}))

    await embedder.close()
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
