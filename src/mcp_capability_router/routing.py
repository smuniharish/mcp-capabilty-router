from __future__ import annotations

from collections.abc import Callable, Iterable

from .models import Capability, CapabilityType

Filter = Callable[[Capability], bool]


def filter_capabilities(
    capabilities: Iterable[Capability],
    *,
    type: CapabilityType | None = None,
    server_id: str | None = None,
    tags: set[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> list[Capability]:
    result = []
    for capability in capabilities:
        if type is not None and capability.type != type:
            continue
        if server_id is not None and capability.server_id != server_id:
            continue
        if tags is not None and not tags.issubset(capability.tags):
            continue
        if metadata is not None and any(
            capability.metadata.get(k) != v for k, v in metadata.items()
        ):
            continue
        if capability.available:
            result.append(capability)
    return result


def rank_capabilities(capabilities: Iterable[Capability], query: str) -> list[Capability]:
    terms = {term.lower() for term in query.split() if term}

    def score(capability: Capability) -> tuple[int, str]:
        haystack = (
            f"{capability.name} {capability.description} "
            f"{getattr(capability, 'uri', '')} {' '.join(capability.tags)}"
        ).lower()
        return (sum(term in haystack for term in terms), capability.capability_id)

    ranked = sorted(capabilities, key=score, reverse=True)
    return [capability for capability in ranked if not terms or score(capability)[0] > 0]
