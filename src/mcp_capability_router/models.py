from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CapabilityType(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    PROMPT = "prompt"


@dataclass(frozen=True, slots=True)
class Capability:
    capability_id: str
    server_id: str
    type: CapabilityType
    name: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: frozenset[str] = frozenset()
    schema: dict[str, Any] | None = None
    version: str | None = None
    available: bool = True
    # Capability IDs this capability depends on; used for dependency-aware refresh planning.
    depends_on: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class Tool(Capability):
    type: CapabilityType = field(default=CapabilityType.TOOL, init=False)


@dataclass(frozen=True, slots=True)
class Resource(Capability):
    uri: str | None = None
    type: CapabilityType = field(default=CapabilityType.RESOURCE, init=False)


@dataclass(frozen=True, slots=True)
class Prompt(Capability):
    arguments: tuple[str, ...] = ()
    type: CapabilityType = field(default=CapabilityType.PROMPT, init=False)
