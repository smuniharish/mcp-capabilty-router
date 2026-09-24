from __future__ import annotations

import asyncio

import pytest

from mcp_capability_router import CapabilityType, MCPRuntime, RefreshPolicy


class DirectoryAdapter:
    """Simulates a directory/gateway MCP server whose tool result names other servers.

    This models a real pattern used by supervisor agents and LangGraph nodes: a
    "discovery" tool call returns a list of downstream server descriptors, and the
    caller registers those servers with the runtime dynamically, at runtime, based
    on that tool/graph result rather than static configuration.
    """

    def __init__(self, downstream_specs):
        self._downstream_specs = downstream_specs
        self.connected = False

    async def connect(self):
        self.connected = True

    async def close(self):
        self.connected = False

    async def list_tools(self):
        return [{"name": "list_downstream_servers", "description": "list available MCP servers"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        assert name == "list_downstream_servers"
        return {"servers": self._downstream_specs}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


class DownstreamAdapter:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.connect_count = 0

    async def connect(self):
        self.connect_count += 1

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": f"{self.prefix}_search", "description": "search records"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


class MutableAdapter:
    """Adapter whose tool list changes over time, simulating server-side updates."""

    def __init__(self):
        self.tool_names: list[str] = ["initial_tool"]
        self.connect_count = 0
        self.list_count = 0

    async def connect(self):
        self.connect_count += 1

    async def close(self):
        pass

    async def list_tools(self):
        self.list_count += 1
        return [{"name": name, "description": "mutable tool"} for name in self.tool_names]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        return {"name": name, "arguments": arguments}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


@pytest.mark.asyncio
async def test_dynamic_server_registration_from_tool_result():
    """New servers are registered at runtime based on a prior tool/graph result."""
    directory = DirectoryAdapter(
        downstream_specs=[
            {"server_id": "reports", "prefix": "reports"},
            {"server_id": "billing", "prefix": "billing"},
        ]
    )
    downstream_adapters = {
        "reports": DownstreamAdapter("reports"),
        "billing": DownstreamAdapter("billing"),
    }

    async with MCPRuntime() as runtime:
        await runtime.register_server("directory", lambda: directory)
        await runtime.refresh_server("directory")

        discovery = await runtime.retrieve("list_downstream_servers", type=CapabilityType.TOOL)
        assert len(discovery) == 1

        # The tool result drives which servers get registered next - this is the
        # "dynamic server registration from a tool/graph result" acceptance path.
        discovery_result = await runtime.execute(discovery[0].capability_id)
        for spec in discovery_result["servers"]:
            adapter = downstream_adapters[spec["server_id"]]
            await runtime.register_server(spec["server_id"], lambda adapter=adapter: adapter)
            await runtime.refresh_server(spec["server_id"])

        reports_tools = await runtime.retrieve("search", server_id="reports")
        billing_tools = await runtime.retrieve("search", server_id="billing")
        assert len(reports_tools) == 1
        assert len(billing_tools) == 1
        assert downstream_adapters["reports"].connect_count == 1
        assert downstream_adapters["billing"].connect_count == 1


@pytest.mark.asyncio
async def test_query_driven_refresh_only_refreshes_on_cache_miss():
    """query() should refresh a named server lazily, only when there is no cached match."""
    adapter = DownstreamAdapter("alpha")
    async with MCPRuntime() as runtime:
        await runtime.register_server("alpha", lambda: adapter)

        # Nothing discovered yet: the query misses and triggers a refresh of "alpha".
        first = await runtime.query("search", refresh_servers=["alpha"])
        assert len(first) == 1
        assert adapter.connect_count == 1

        # Metadata is now cached, so a second query with the same hint must not refresh again.
        second = await runtime.query("search", refresh_servers=["alpha"])
        assert len(second) == 1
        assert adapter.connect_count == 1


@pytest.mark.asyncio
async def test_query_driven_refresh_returns_empty_when_still_unmatched():
    """query() refreshes the named servers but still returns no matches for an unrelated term."""
    adapter = DownstreamAdapter("alpha")
    async with MCPRuntime() as runtime:
        await runtime.register_server("alpha", lambda: adapter)
        results = await runtime.query("nonexistent_capability", refresh_servers=["alpha"])
        assert results == []
        assert adapter.connect_count == 1


@pytest.mark.asyncio
async def test_refresh_policy_automatically_refreshes_on_query_miss():
    adapter = DownstreamAdapter("alpha")
    async with MCPRuntime() as runtime:
        await runtime.register_server(
            "alpha",
            lambda: adapter,
            refresh=RefreshPolicy(on_query_miss=True),
        )

        matches = await runtime.query("search")

        assert len(matches) == 1
        assert adapter.connect_count == 1


@pytest.mark.asyncio
async def test_refresh_policy_reacts_to_change_events_without_application_listener():
    adapter = MutableAdapter()
    change_events: asyncio.Queue[object] = asyncio.Queue()

    async with MCPRuntime() as runtime:
        await runtime.register_server(
            "mutable",
            lambda: adapter,
            refresh=RefreshPolicy(on_register=True, change_events=change_events),
        )
        assert len(await runtime.retrieve("initial")) == 1

        adapter.tool_names.append("added_tool")
        await change_events.put(object())

        for _ in range(50):
            if await runtime.retrieve("added_tool"):
                break
            await asyncio.sleep(0.01)

        assert len(await runtime.retrieve("added_tool")) == 1
        assert adapter.list_count == 2


@pytest.mark.asyncio
async def test_refresh_policy_periodically_reconciles_until_runtime_closes():
    adapter = MutableAdapter()
    runtime = MCPRuntime()
    await runtime.register_server(
        "mutable",
        lambda: adapter,
        refresh=RefreshPolicy(on_register=True, interval=0.01),
    )
    adapter.tool_names.append("periodic_tool")

    for _ in range(50):
        if await runtime.retrieve("periodic_tool"):
            break
        await asyncio.sleep(0.01)

    assert len(await runtime.retrieve("periodic_tool")) == 1
    await runtime.close()
    count_after_close = adapter.list_count
    await asyncio.sleep(0.03)
    assert adapter.list_count == count_after_close


def test_refresh_policy_rejects_non_positive_interval():
    with pytest.raises(ValueError, match="greater than zero"):
        RefreshPolicy(interval=0)
