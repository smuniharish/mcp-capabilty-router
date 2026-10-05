from __future__ import annotations

from mcp_capability_router import CapabilityRegistry, CapabilityType, InMemoryRegistry
from tests.support import capability_ids, prompt, resource, tool


async def test_registry_implements_the_contract() -> None:
    assert isinstance(InMemoryRegistry(), CapabilityRegistry)


async def test_upsert_get_and_list_with_filters() -> None:
    registry = InMemoryRegistry()
    await registry.upsert_many(
        [
            tool("fs", "read"),
            resource("fs", "file:///a", "a"),
            prompt("git", "plan"),
            tool("git", "status"),
        ]
    )
    assert (await registry.get("fs:tool:read")) == tool("fs", "read")
    assert await registry.get("missing") is None
    assert capability_ids(await registry.list()) == [
        "fs:tool:read",
        "fs:resource:file:///a",
        "git:prompt:plan",
        "git:tool:status",
    ]
    assert capability_ids(await registry.list(server_id="git")) == [
        "git:prompt:plan",
        "git:tool:status",
    ]
    assert capability_ids(await registry.list(type=CapabilityType.TOOL)) == [
        "fs:tool:read",
        "git:tool:status",
    ]
    assert capability_ids(
        await registry.list(server_id="fs", type=CapabilityType.RESOURCE)
    ) == ["fs:resource:file:///a"]
    assert await registry.list(server_id="unknown") == []


async def test_upsert_replaces_and_moves_between_servers() -> None:
    registry = InMemoryRegistry()
    await registry.upsert_many([tool("a", "t", "old")])
    await registry.upsert_many([tool("a", "t", "new")])
    assert (await registry.get("a:tool:t")).description == "new"  # type: ignore[union-attr]
    moved = tool("a", "t").__class__(
        capability_id="a:tool:t", server_id="b", name="t", description="moved"
    )
    await registry.upsert_many([moved])
    assert await registry.list(server_id="a") == []
    assert await registry.list(server_id="b") == [moved]


async def test_remove_and_remove_server() -> None:
    registry = InMemoryRegistry()
    await registry.upsert_many([tool("a", "x"), tool("a", "y"), tool("b", "z")])
    await registry.remove("a:tool:x")
    await registry.remove("a:tool:x")
    assert capability_ids(await registry.list(server_id="a")) == ["a:tool:y"]
    await registry.remove("a:tool:y")
    assert await registry.list(server_id="a") == []
    await registry.remove_server("b")
    await registry.remove_server("b")
    assert await registry.list() == []


async def test_close_clears_everything() -> None:
    registry = InMemoryRegistry()
    await registry.upsert_many([tool("a", "x")])
    await registry.close()
    assert await registry.list() == []
    assert await registry.get("a:tool:x") is None
