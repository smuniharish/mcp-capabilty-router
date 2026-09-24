"""Optional abstract base class for a pluggable capability-embedding model.

Vector-backed retrievers (for example ``QdrantCapabilityRetriever`` in
``examples/vector_retrieval_qdrant.py``) accept an injected ``embed_fn``:
``Callable[[str], Awaitable[list[float]]]``. A bare async function or callable object
already satisfies that shape and needs no base class. :class:`CapabilityEmbedder` exists
purely as a convenience template for implementers who want an explicit, enforced contract
(one abstract method, a default batching helper, and built-in ``Callable`` compatibility)
instead of hand-rolling the ``__call__`` boilerplate every time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence


class CapabilityEmbedder(ABC):
    """Turns capability text into a fixed-size embedding vector.

    Subclass this and implement :meth:`embed`. The instance is then directly usable
    anywhere an ``embed_fn`` callable is expected, because :class:`CapabilityEmbedder` is
    itself callable (``__call__`` delegates to :meth:`embed`).
    """

    @abstractmethod
    async def embed(self, text: str) -> list[float]:
        """Return the embedding vector for ``text``."""

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed several texts. Defaults to sequential calls; override for real batching."""
        return [await self.embed(text) for text in texts]

    async def __call__(self, text: str) -> list[float]:
        return await self.embed(text)
