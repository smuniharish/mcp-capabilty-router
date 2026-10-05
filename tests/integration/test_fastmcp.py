"""End-to-end tests against real MCP servers running in process through FastMCP."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import StructuredTool, ToolException
from mcp import types
from mcp.shared.exceptions import MCPError
from refresh_engine import RefreshMode, RefreshStatus

from mcp_capability_router import (
    CapabilityRoutingMiddleware,
    FastMCPAdapter,
    HealthState,
    InvalidRequestError,
    MCPAdapter,
    MCPRuntime,
    ProtocolError,
    RefreshError,
    RefreshPolicy,
    Resource,
    ServerConnectionError,
    ToolExecutionError,
)
from tests.support import ScriptedChatModel, capability_ids, demo_server, tool_messages


@pytest.fixture
async def adapter() -> AsyncIterator[FastMCPAdapter]:
    instance = FastMCPAdapter(demo_server())
    await instance.connect()
    yield instance
    await instance.close()


class TestFastMCPAdapter:
    async def test_implements_the_adapter_contract(
        self, adapter: FastMCPAdapter
    ) -> None:
        assert isinstance(adapter, MCPAdapter)
        assert isinstance(adapter.client, Client)
        await adapter.connect()

    async def test_lists_metadata_only(self, adapter: FastMCPAdapter) -> None:
        tools = await adapter.list_tools()
        resources = await adapter.list_resources()
        prompts = await adapter.list_prompts()
        assert sorted(tool.name for tool in tools) == ["add", "fail"]
        assert {resource.uri for resource in resources} == {
            "resource://notes/readme",
            "resource://images/pixel",
        }
        assert all(isinstance(resource, types.Resource) for resource in resources)
        assert [prompt.name for prompt in prompts] == ["summarize"]

    async def test_calls_tools_through_langchain(self, adapter: FastMCPAdapter) -> None:
        message = await adapter.call_tool("add", {"a": 2, "b": 40})
        assert isinstance(message, ToolMessage)
        assert message.status == "success"
        assert message.artifact == {"structured_content": {"result": 42}}
        with pytest.raises(ToolExecutionError, match="no such record"):
            await adapter.call_tool("fail", {"reason": "no such record"})
        with pytest.raises(ToolExecutionError):
            await adapter.call_tool("add", {"a": "not a number"})
        with pytest.raises(InvalidRequestError, match="no tool named 'missing'"):
            await adapter.call_tool("missing", {})

    async def test_reads_resources_and_renders_prompts(
        self, adapter: FastMCPAdapter
    ) -> None:
        [text] = await adapter.read_resource("resource://notes/readme")
        assert isinstance(text, types.TextResourceContents)
        assert (text.text, text.mime_type) == ("# Hello", "text/markdown")
        [blob] = await adapter.read_resource("resource://images/pixel")
        assert isinstance(blob, types.BlobResourceContents)
        assert base64.b64decode(blob.blob) == b"\x89PNG\r\n"
        rendered = await adapter.get_prompt("summarize", {"topic": "MCP"})
        assert isinstance(rendered, types.GetPromptResult)
        assert rendered.messages[0].content.text == "Summarize MCP in a neutral tone."  # type: ignore[union-attr]
        with pytest.raises(InvalidRequestError, match="Resource not found"):
            await adapter.read_resource("resource://missing")
        with pytest.raises(InvalidRequestError, match="Unknown prompt"):
            await adapter.get_prompt("missing", {})

    async def test_rejects_tools_that_were_not_converted_to_coroutines(
        self, adapter: FastMCPAdapter
    ) -> None:
        adapter._tools["odd"] = StructuredTool.from_function(  # type: ignore[assignment]
            func=lambda: "sync", name="odd", description="A synchronous tool."
        )
        with pytest.raises(ProtocolError, match="was converted to StructuredTool"):
            await adapter.call_tool("odd", {})

    @pytest.mark.parametrize(
        ("error", "message"),
        [
            (ToolException("plain failure"), "plain failure"),
            (ToolException(), "tool 'broken' failed"),
        ],
    )
    async def test_reports_tool_errors(
        self, adapter: FastMCPAdapter, error: ToolException, message: str
    ) -> None:
        async def failing(**arguments: Any) -> tuple[Any, Any]:
            raise error

        adapter._tools["broken"] = StructuredTool(
            name="broken",
            description="Always fails.",
            args_schema={"type": "object", "properties": {}},
            coroutine=failing,
            response_format="content_and_artifact",
        )
        with pytest.raises(ToolExecutionError) as raised:
            await adapter.call_tool("broken", {})
        assert str(raised.value) == message

    async def test_passes_arguments_named_like_langchain_parameters(
        self, adapter: FastMCPAdapter
    ) -> None:
        received: list[dict[str, Any]] = []

        async def record(**arguments: Any) -> tuple[Any, Any]:
            received.append(arguments)
            return [{"type": "text", "text": "ok"}], None

        adapter._tools["apply"] = StructuredTool(
            name="apply",
            description="Records its arguments.",
            args_schema={"type": "object", "properties": {}},
            coroutine=record,
            response_format="content_and_artifact",
        )
        arguments = {"config": {"replicas": 3}, "run_manager": "x", "callbacks": 1}
        message = await adapter.call_tool("apply", arguments)
        assert received == [arguments]
        assert (message.name, message.text, message.artifact) == ("apply", "ok", None)

    async def test_lists_only_the_kinds_a_server_offers(self) -> None:
        listed: list[str] = []

        async def resources() -> list[types.Resource]:
            listed.append("resources")
            return []

        async def prompts() -> list[types.Prompt]:
            raise MCPError(types.METHOD_NOT_FOUND, "Method not found")

        async def tools() -> list[types.Tool]:
            raise MCPError(types.INVALID_PARAMS, "bad cursor")

        adapter = FastMCPAdapter(demo_server())
        adapter._client = SimpleNamespace(  # type: ignore[assignment]
            server_capabilities=types.ServerCapabilities(tools=None),
            list_tools=tools,
            list_resources=resources,
            list_prompts=prompts,
        )
        assert await adapter.list_tools() == []
        adapter._client.server_capabilities = None  # type: ignore[misc]
        assert await adapter.list_resources() == []
        assert await adapter.list_prompts() == []
        assert listed == ["resources"]
        with pytest.raises(InvalidRequestError, match="bad cursor"):
            await adapter.list_tools()

    async def test_reloads_tool_definitions_after_reconnecting(self) -> None:
        server = demo_server()
        adapter = FastMCPAdapter(Client(server))
        await adapter.connect()
        await adapter.list_tools()
        await adapter.call_tool("add", {"a": 1, "b": 1})
        await adapter.close()
        await adapter.close()
        await adapter.connect()
        message = await adapter.call_tool("add", {"a": 1, "b": 2})
        assert message.artifact == {"structured_content": {"result": 3}}
        await adapter.close()

    async def test_session_is_shared_across_tasks(self) -> None:
        adapter = FastMCPAdapter(demo_server())
        await asyncio.create_task(adapter.connect())
        results = await asyncio.gather(
            *(adapter.call_tool("add", {"a": index, "b": index}) for index in range(5))
        )
        assert [message.artifact for message in results] == [
            {"structured_content": {"result": 2 * index}} for index in range(5)
        ]
        await asyncio.create_task(adapter.close())
        assert not adapter.client.is_connected()


class TestRuntimeWithFastMCP:
    async def test_full_routing_flow(self) -> None:
        async with MCPRuntime() as runtime:
            await runtime.register_mcp(
                "demo", demo_server(), refresh=RefreshPolicy(on_register=True)
            )
            capabilities = await runtime.retrieve("", limit=10)
            assert capability_ids(capabilities) == [
                "demo:prompt:summarize",
                "demo:resource:resource://images/pixel",
                "demo:resource:resource://notes/readme",
                "demo:tool:add",
                "demo:tool:fail",
            ]
            [best] = await runtime.retrieve("add two numbers", limit=1)
            assert best.capability_id == "demo:tool:add"
            assert best.tags == frozenset({"math"})
            assert best.metadata["annotations"] == {"read_only_hint": True}
            message = await runtime.execute("demo:tool:add", {"a": 20, "b": 22})
            assert message.artifact == {"structured_content": {"result": 42}}
            with pytest.raises(ToolExecutionError):
                await runtime.execute("demo:tool:fail", {"reason": "nope"})
            assert await runtime.health("demo") is HealthState.HEALTHY
            readme = await runtime.resolve("demo:resource:resource://notes/readme")
            assert isinstance(readme, Resource)
            assert readme.mime_type == "text/markdown"
            [contents] = await runtime.read_resource(readme.capability_id)
            assert contents.text == "# Hello"
            rendered = await runtime.get_prompt(
                "demo:prompt:summarize", {"topic": "MCP"}
            )
            assert rendered.messages[0].content.text.startswith("Summarize MCP")

    async def test_refresh_follows_server_changes(self) -> None:
        server = demo_server()
        async with MCPRuntime() as runtime:
            await runtime.register_mcp(
                "demo", server, refresh=RefreshPolicy(on_register=True)
            )

            def subtract(a: int, b: int) -> int:
                """Subtract two integers."""
                return a - b

            server.add_tool(subtract)
            result = await runtime.refresh_server("demo")
            assert (result.status, result.added_count) == (RefreshStatus.SUCCESS, 1)
            message = await runtime.execute("demo:tool:subtract", {"a": 5, "b": 3})
            assert message.artifact == {"structured_content": {"result": 2}}
            result = await runtime.refresh_server("demo", mode=RefreshMode.FULL)
            assert result.refreshed_count == 6

    async def test_unreachable_servers_fail_with_connection_errors(self) -> None:
        async with MCPRuntime(operation_timeout=30) as runtime:
            await runtime.register_mcp("offline", "http://127.0.0.1:9/mcp")
            with pytest.raises(RefreshError) as raised:
                await runtime.refresh_server("offline")
            assert isinstance(raised.value.__cause__, ServerConnectionError)
            assert await runtime.health("offline") is HealthState.DEGRADED

    async def test_agent_calls_mcp_tools_through_the_middleware(self) -> None:
        async with MCPRuntime() as runtime:
            await runtime.register_mcp(
                "demo", demo_server(), refresh=RefreshPolicy(on_register=True)
            )
            model = ScriptedChatModel(
                responses=[
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "add",
                                "args": {"a": 2, "b": 3},
                                "id": "call-1",
                                "type": "tool_call",
                            },
                            {
                                "name": "fail",
                                "args": {"reason": "out of stock"},
                                "id": "call-2",
                                "type": "tool_call",
                            },
                        ],
                    ),
                    AIMessage(content="The sum is 5."),
                ]
            )
            agent = create_agent(
                model,
                tools=[],
                middleware=[CapabilityRoutingMiddleware(runtime, server_id="demo")],
            )
            result = await agent.ainvoke(
                {"messages": [HumanMessage("add two numbers, or fail")]}
            )
            assert model.calls[0] == ["add", "fail"]
            added, failed = tool_messages(result)
            assert added.artifact == {"structured_content": {"result": 5}}
            assert failed.status == "error"
            assert "out of stock" in str(failed.content)
