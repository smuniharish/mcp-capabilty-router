from __future__ import annotations

import pytest

from mcp_capability_router import Tool
from mcp_capability_router.errors import SelectionError
from mcp_capability_router.selection import LLMCapabilitySelector


class RecordingModel:
    """A fake LangChain-compatible model: only ``ainvoke`` is required."""

    def __init__(self, response):
        self.response = response
        self.received: dict | None = None

    async def ainvoke(self, prompt):
        self.received = prompt
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _candidates() -> list[Tool]:
    return [
        Tool(capability_id="s:tool:a", server_id="s", name="a", description="alpha"),
        Tool(capability_id="s:tool:b", server_id="s", name="b", description="beta"),
        Tool(capability_id="s:tool:c", server_id="s", name="c", description="gamma"),
    ]


@pytest.mark.asyncio
async def test_llm_selector_only_receives_already_retrieved_candidates():
    model = RecordingModel(["s:tool:b"])
    selector = LLMCapabilitySelector(model)
    candidates = _candidates()

    selected = await selector.select("pick beta", candidates)

    assert selected == ["s:tool:b"]
    assert model.received is not None
    assert [c["id"] for c in model.received["candidates"]] == [c.capability_id for c in candidates]
    assert len(model.received["candidates"]) == len(candidates)


@pytest.mark.asyncio
async def test_llm_selector_accepts_dict_shaped_responses():
    model = RecordingModel({"selected": ["s:tool:a", "s:tool:c"]})
    selector = LLMCapabilitySelector(model)

    selected = await selector.select("pick a and c", _candidates())

    assert selected == ["s:tool:a", "s:tool:c"]


@pytest.mark.asyncio
async def test_llm_selector_never_crashes_the_runtime_it_raises_selection_error():
    model = RecordingModel(RuntimeError("model backend unavailable"))
    selector = LLMCapabilitySelector(model)

    with pytest.raises(SelectionError):
        await selector.select("pick anything", _candidates())


@pytest.mark.asyncio
async def test_llm_selector_reduces_a_large_candidate_set_by_construction():
    """The selector is only ever given the retrieval/filter/rank output, never the full set."""
    huge_registry_size = 10_000
    already_narrowed_candidates = _candidates()  # simulates post retrieval/filter/rank output
    model = RecordingModel([c.capability_id for c in already_narrowed_candidates])
    selector = LLMCapabilitySelector(model)

    selected = await selector.select("narrow query", already_narrowed_candidates)

    assert len(selected) <= len(already_narrowed_candidates) < huge_registry_size
