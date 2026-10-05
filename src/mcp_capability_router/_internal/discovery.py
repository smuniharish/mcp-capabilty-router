"""Conversion of MCP listings into capability records."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from ..contracts import MCPAdapter
from ..errors import DiscoveryError
from ..models import (
    Capability,
    CapabilityType,
    Prompt,
    PromptArgument,
    Resource,
    Tool,
    make_capability_id,
)
from .concurrency import gather_or_cancel

if TYPE_CHECKING:
    from mcp import types

DEPENDS_ON_KEY = "depends_on"
"""Key of the `_meta` entry that lists the IDs a capability depends on."""


async def discover_capabilities(
    adapter: MCPAdapter, server_id: str
) -> list[Capability]:
    """List the tools, resources, and prompts of a server as capabilities.

    Raises:
        DiscoveryError: If the listing is malformed or names a capability twice.
    """
    from mcp import types

    tools, resources, prompts = await gather_or_cancel(
        adapter.list_tools(), adapter.list_resources(), adapter.list_prompts()
    )
    capabilities: list[Capability] = [
        *(_tool(server_id, item) for item in _items(tools, types.Tool, server_id)),
        *(
            _resource(server_id, item)
            for item in _items(resources, types.Resource, server_id)
        ),
        *(
            _prompt(server_id, item)
            for item in _items(prompts, types.Prompt, server_id)
        ),
    ]
    seen: set[str] = set()
    for capability in capabilities:
        if capability.capability_id in seen:
            msg = (
                f"server {server_id!r} listed the {capability.type} "
                f"{capability.name!r} more than once"
            )
            raise DiscoveryError(msg)
        seen.add(capability.capability_id)
    return capabilities


def _items[T](items: Iterable[object], kind: type[T], server_id: str) -> list[T]:
    result: list[T] = []
    for item in items:
        if not isinstance(item, kind):
            msg = (
                f"server {server_id!r} listed {type(item).__name__}, expected "
                f"mcp.types.{kind.__name__}"
            )
            raise DiscoveryError(msg)
        result.append(item)
    return result


def _tool(server_id: str, tool: types.Tool) -> Tool:
    meta = dict(tool.meta or {})
    annotations = (
        tool.annotations.model_dump(exclude_none=True, mode="json")
        if tool.annotations
        else {}
    )
    return Tool(
        capability_id=make_capability_id(server_id, CapabilityType.TOOL, tool.name),
        server_id=server_id,
        name=tool.name,
        title=tool.title or annotations.get("title"),
        description=tool.description or "",
        tags=_tags(meta),
        metadata=_metadata(annotations, meta),
        depends_on=_depends_on(meta, server_id, tool.name),
        input_schema=dict(tool.input_schema),
        output_schema=dict(tool.output_schema) if tool.output_schema else None,
    )


def _resource(server_id: str, resource: types.Resource) -> Resource:
    meta = dict(resource.meta or {})
    annotations = (
        resource.annotations.model_dump(exclude_none=True, mode="json")
        if resource.annotations
        else {}
    )
    return Resource(
        capability_id=make_capability_id(
            server_id, CapabilityType.RESOURCE, resource.uri
        ),
        server_id=server_id,
        name=resource.name,
        title=resource.title,
        description=resource.description or "",
        tags=_tags(meta),
        metadata=_metadata(annotations, meta),
        depends_on=_depends_on(meta, server_id, resource.uri),
        uri=resource.uri,
        mime_type=resource.mime_type,
    )


def _prompt(server_id: str, prompt: types.Prompt) -> Prompt:
    meta = dict(prompt.meta or {})
    return Prompt(
        capability_id=make_capability_id(server_id, CapabilityType.PROMPT, prompt.name),
        server_id=server_id,
        name=prompt.name,
        title=prompt.title,
        description=prompt.description or "",
        tags=_tags(meta),
        metadata=_metadata({}, meta),
        depends_on=_depends_on(meta, server_id, prompt.name),
        arguments=tuple(
            PromptArgument(
                name=argument.name,
                description=argument.description or "",
                required=bool(argument.required),
            )
            for argument in prompt.arguments or ()
        ),
    )


def _metadata(
    annotations: Mapping[str, Any], meta: Mapping[str, Any]
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if annotations:
        metadata["annotations"] = dict(annotations)
    if meta:
        metadata["meta"] = dict(meta)
    return metadata


def _tags(meta: Mapping[str, Any]) -> frozenset[str]:
    """Read tags from the `_meta.fastmcp.tags` convention of FastMCP servers."""
    fastmcp = meta.get("fastmcp")
    tags = fastmcp.get("tags") if isinstance(fastmcp, Mapping) else None
    if isinstance(tags, Sequence) and not isinstance(tags, str):
        return frozenset(str(tag) for tag in tags)
    return frozenset()


def _depends_on(meta: Mapping[str, Any], server_id: str, name: str) -> frozenset[str]:
    value = meta.get(DEPENDS_ON_KEY)
    if value is None:
        return frozenset()
    if isinstance(value, str) or not isinstance(value, Sequence):
        msg = (
            f"server {server_id!r} declared {DEPENDS_ON_KEY!r} of {name!r} as "
            f"{type(value).__name__}, expected a list of capability IDs"
        )
        raise DiscoveryError(msg)
    return frozenset(str(item) for item in value)
