"""Capability records and the enumerations that describe them."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CapabilityType(StrEnum):
    """The kind of capability that an MCP server offers."""

    TOOL = "tool"
    """A function that the model can call."""

    RESOURCE = "resource"
    """A piece of data that the application can read."""

    PROMPT = "prompt"
    """A prompt template that the application can render."""


class HealthState(StrEnum):
    """The health of a server, derived from its circuit breakers.

    The states are ordered from best to worst: `HEALTHY`, `DEGRADED`, `RECOVERING`,
    and `UNHEALTHY`.
    """

    HEALTHY = "healthy"
    """No recent failures."""

    DEGRADED = "degraded"
    """Recent operations failed, but the circuit is still closed."""

    RECOVERING = "recovering"
    """The circuit admits trial calls to find out whether the server recovered."""

    UNHEALTHY = "unhealthy"
    """The circuit is open and operations are rejected without calling the server."""


def make_capability_id(server_id: str, type: CapabilityType, name: str) -> str:
    """Build the ID of a discovered capability.

    The ID has the form `<server_id>:<type>:<name>`, where `name` is the tool or
    prompt name, or the resource URI.

    Args:
        server_id: The ID of the server that offers the capability.
        type: The kind of capability.
        name: The tool or prompt name, or the resource URI.

    Returns:
        The capability ID.
    """
    return f"{server_id}:{CapabilityType(type).value}:{name}"


@dataclass(frozen=True, slots=True, kw_only=True)
class Capability:
    """Metadata of one capability offered by an MCP server.

    Records are immutable snapshots of what a server advertised during discovery.
    Use the subclasses `Tool`, `Resource`, and `Prompt`; they set `type`.

    Attributes:
        capability_id: Unique ID; see `make_capability_id`.
        server_id: ID of the server that offers the capability.
        type: The kind of capability.
        name: Name of the tool or prompt, or the name of the resource.
        title: Human-readable title, if the server provides one.
        description: Description that the server provides.
        tags: Tags used for retrieval and for targeted refreshes.
        metadata: Additional metadata, such as MCP annotations.
        depends_on: IDs of capabilities that this capability depends on.
    """

    capability_id: str
    server_id: str
    type: CapabilityType
    name: str
    title: str | None = None
    description: str = ""
    tags: frozenset[str] = frozenset()
    metadata: Mapping[str, Any] = field(default_factory=dict, hash=False)
    depends_on: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class Tool(Capability):
    """A tool that the model can call.

    Attributes:
        input_schema: JSON Schema of the tool arguments.
        output_schema: JSON Schema of the structured result, if declared.
    """

    type: CapabilityType = field(default=CapabilityType.TOOL, init=False)
    input_schema: Mapping[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}}, hash=False
    )
    output_schema: Mapping[str, Any] | None = field(default=None, hash=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class Resource(Capability):
    """A resource that the application can read.

    Attributes:
        uri: URI of the resource.
        mime_type: MIME type of the content, if declared.
    """

    type: CapabilityType = field(default=CapabilityType.RESOURCE, init=False)
    uri: str
    mime_type: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PromptArgument:
    """An argument of a prompt template.

    Attributes:
        name: Name of the argument.
        description: Description of the argument.
        required: Whether the argument must be provided.
    """

    name: str
    description: str = ""
    required: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class Prompt(Capability):
    """A prompt template that the application can render.

    Attributes:
        arguments: The arguments that the template accepts.
    """

    type: CapabilityType = field(default=CapabilityType.PROMPT, init=False)
    arguments: tuple[PromptArgument, ...] = ()
