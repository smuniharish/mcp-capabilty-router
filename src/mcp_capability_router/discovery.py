from __future__ import annotations

from typing import Any

from .errors import DiscoveryError
from .models import Capability, Prompt, Resource, Tool
from .server import ServerHandle


def _value(item: Any, name: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _capability_id(server_id: str, kind: str, name: str) -> str:
    return f"{server_id}:{kind}:{name}"


async def discover_server(server: ServerHandle) -> list[Capability]:
    try:
        adapter = await server.connect()
        tools, resources, prompts = await __import__("asyncio").gather(
            adapter.list_tools(), adapter.list_resources(), adapter.list_prompts()
        )
    except Exception as exc:
        raise DiscoveryError(f"Discovery failed for server {server.server_id}") from exc

    result: list[Capability] = []
    for item in tools:
        name = str(_value(item, "name", ""))
        result.append(
            Tool(
                capability_id=_capability_id(server.server_id, "tool", name),
                server_id=server.server_id,
                name=name,
                description=str(_value(item, "description", "")),
                metadata=dict(_value(item, "metadata", {}) or {}),
                schema=_value(item, "inputSchema", _value(item, "schema")),
                depends_on=frozenset(_value(item, "dependencies", ()) or ()),
            )
        )
    for item in resources:
        uri = str(_value(item, "uri", _value(item, "name", "")))
        result.append(
            Resource(
                capability_id=_capability_id(server.server_id, "resource", uri),
                server_id=server.server_id,
                name=str(_value(item, "name", uri)),
                uri=uri,
                description=str(_value(item, "description", "")),
                metadata=dict(_value(item, "metadata", {}) or {}),
                depends_on=frozenset(_value(item, "dependencies", ()) or ()),
            )
        )
    for item in prompts:
        name = str(_value(item, "name", ""))
        args = _value(item, "arguments", ()) or ()
        result.append(
            Prompt(
                capability_id=_capability_id(server.server_id, "prompt", name),
                server_id=server.server_id,
                name=name,
                description=str(_value(item, "description", "")),
                arguments=tuple(str(_value(arg, "name", arg)) for arg in args),
                depends_on=frozenset(_value(item, "dependencies", ()) or ()),
            )
        )
    return result
