from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from .errors import SelectionError
from .models import Capability


class CapabilitySelector(Protocol):
    async def select(self, query: str, candidates: Sequence[Capability]) -> Sequence[str]: ...


class LLMCapabilitySelector:
    """Adapter for an application-supplied LangChain-compatible model.

    The model only receives the already retrieved candidate set; provider configuration
    remains the application's responsibility.
    """

    def __init__(self, model: Any):
        self.model = model

    async def select(self, query: str, candidates: Sequence[Capability]) -> Sequence[str]:
        prompt = {
            "query": query,
            "candidates": [
                {
                    "id": c.capability_id,
                    "name": c.name,
                    "type": c.type.value,
                    "description": c.description,
                }
                for c in candidates
            ],
        }
        try:
            result = await self.model.ainvoke(prompt)
        except Exception as exc:
            raise SelectionError("Capability selector failed") from exc
        if isinstance(result, dict):
            result = result.get("selected", [])
        return [str(item) for item in result]
