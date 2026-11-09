"""Tests of the MCP gateway: the router served as one MCP server."""

from __future__ import annotations

import base64
import importlib.util
from typing import TYPE_CHECKING, Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.transforms import Namespace
from fastmcp.utilities.types import Image
from mcp import types
from mcp.shared.exceptions import MCPError

from mcp_capability_router import (
    ConfigurationError,
    MCPRuntime,
    RefreshPolicy,
    RouterProvider,
    RouterSearchTransform,
    RuntimeClosedError,
)
from mcp_capability_router.gateway import _describe
from tests.support import FakeAdapter, demo_server, mcp_prompt, mcp_resource, mcp_tool

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def files_server() -> FastMCP:
    server = FastMCP("files")

    @server.tool(annotations={"readOnlyHint": True})
    def read_text_file(path: str) -> str:
        """Read the contents of a text file."""
        return f"contents of {path}"

    @server.resource("resource://notes/readme", mime_type="text/plain")
    def readme() -> str:
        return "files readme"

    return server


def weather_server() -> FastMCP:
    server = FastMCP("weather")

    @server.tool
    def get_forecast(city: str) -> dict[str, Any]:
        """Weather forecast for a city."""
        return {"city": city, "temp": 21}

    @server.tool
    def radar(city: str) -> Image:
        """Radar image for a city."""
        return Image(data=b"\x89PNG", format="png")

    return server


@pytest.fixture
async def runtime() -> AsyncIterator[MCPRuntime]:
    async with MCPRuntime() as instance:
        policy = RefreshPolicy(on_register=True)
        await instance.register_mcp("demo", demo_server(), refresh=policy)
        await instance.register_mcp("files", files_server(), refresh=policy)
        await instance.register_mcp("weather", weather_server(), refresh=policy)
        yield instance


class TestCatalogMode:
    async def test_lists_every_capability(self, runtime: MCPRuntime) -> None:
        async with Client(runtime.as_mcp_server(mode="catalog")) as client:
            tools = {tool.name: tool for tool in await client.list_tools()}
            assert list(tools) == [
                "demo_add",
                "demo_fail",
                "files_read_text_file",
                "weather_get_forecast",
                "weather_radar",
            ]
            add = tools["demo_add"]
            assert add.description == "Add two integers."
            assert add.annotations is not None
            assert add.annotations.read_only_hint is True
            assert add.input_schema["required"] == ["a", "b"]
            assert add.meta is not None
            assert add.meta["mcp_capability_router"] == {
                "capability_id": "demo:tool:add",
                "server_id": "demo",
            }
            assert add.meta["fastmcp"]["tags"] == ["math"]
            resources = await client.list_resources()
            assert [(r.uri, r.mime_type) for r in resources] == [
                ("resource://images/pixel", "image/png"),
                ("resource://notes/readme", "text/markdown"),
            ]
            prompts = await client.list_prompts()
            assert [(p.name, [a.name for a in p.arguments or []]) for p in prompts] == [
                ("demo_summarize", ["topic", "tone"])
            ]
            assert prompts[0].arguments is not None
            assert [a.required for a in prompts[0].arguments] == [True, False]

    async def test_calls_tools_through_the_runtime(self, runtime: MCPRuntime) -> None:
        async with Client(runtime.as_mcp_server(mode="catalog")) as client:
            result = await client.call_tool("demo_add", {"a": 2, "b": 40})
            assert (result.data, result.structured_content) == (42, {"result": 42})
            result = await client.call_tool("weather_radar", {"city": "Oslo"})
            [image] = result.content
            assert isinstance(image, types.ImageContent)
            assert (image.mime_type, base64.b64decode(image.data)) == ("image/png", b"\x89PNG")
            failed = await client.call_tool(
                "demo_fail", {"reason": "out of stock"}, raise_on_error=False
            )
            assert failed.is_error
            assert failed.content[0].text == (  # type: ignore[union-attr]
                "ToolExecutionError: Error calling tool 'fail': out of stock"
            )  # type: ignore[union-attr]
            with pytest.raises(ToolError, match="Unknown tool"):
                await client.call_tool("demo_missing", {})

    async def test_reads_resources_and_renders_prompts(self, runtime: MCPRuntime) -> None:
        async with Client(runtime.as_mcp_server(mode="catalog")) as client:
            [text] = await client.read_resource("resource://notes/readme")
            assert isinstance(text, types.TextResourceContents)
            assert (text.text, text.mime_type) == ("# Hello", "text/markdown")
            [blob] = await client.read_resource("resource://images/pixel")
            assert isinstance(blob, types.BlobResourceContents)
            assert base64.b64decode(blob.blob) == b"\x89PNG\r\n"
            rendered = await client.get_prompt("demo_summarize", {"topic": "MCP"})
            assert rendered.messages[0].role == "user"
            assert rendered.messages[0].content.text == "Summarize MCP in a neutral tone."  # type: ignore[union-attr]
            with pytest.raises(MCPError, match="Resource not found"):
                await client.read_resource("resource://missing")
            with pytest.raises(MCPError, match="Unknown prompt"):
                await client.get_prompt("demo_missing", {})
            with pytest.raises(MCPError, match="InvalidRequestError"):
                await client.get_prompt("demo_summarize", {})

    async def test_follows_the_registry(self, runtime: MCPRuntime) -> None:
        async with Client(runtime.as_mcp_server(mode="catalog")) as client:
            await runtime.unregister_server("weather")
            names = [tool.name for tool in await client.list_tools()]
            assert "weather_get_forecast" not in names
            with pytest.raises(ToolError, match="Unknown tool"):
                await client.call_tool("weather_get_forecast", {"city": "Oslo"})


class TestOtherAdapters:
    async def test_serves_results_that_are_not_mcp_objects(self) -> None:
        adapter = FakeAdapter(
            tools=[mcp_tool("echo", "Echo the arguments.")],
            resources=[mcp_resource("memo://a", "a")],
            prompts=[mcp_prompt("greet", arguments=[types.PromptArgument(name="who")])],
        )
        async with MCPRuntime() as runtime:
            await runtime.register_server(
                "fake", lambda: adapter, refresh=RefreshPolicy(on_register=True)
            )
            async with Client(runtime.as_mcp_server(mode="catalog")) as client:
                result = await client.call_tool("fake_echo", {"x": 1})
                assert result.content[0].text == '{"tool":"echo","arguments":{"x":1}}'  # type: ignore[union-attr]
                [contents] = await client.read_resource("memo://a")
                assert isinstance(contents, types.TextResourceContents)
                assert (contents.text, contents.mime_type) == ("contents of memo://a", "text/plain")
                rendered = await client.get_prompt("fake_greet", {"who": "Ada"})
                assert rendered.messages[0].content.text == "prompt greet with {'who': 'Ada'}"  # type: ignore[union-attr]
                adapter.failures["read_resource"] = [TimeoutError()]
                with pytest.raises(MCPError, match="TimeoutError"):
                    await client.read_resource("memo://a")

    async def test_serves_resource_lists_of_any_contents(self) -> None:
        class Listing(FakeAdapter):
            async def read_resource(self, uri: str) -> Any:
                return [
                    types.TextResourceContents(uri=uri, text="text", mime_type="text/csv"),
                    types.BlobResourceContents(uri=uri, blob=base64.b64encode(b"\x00").decode()),
                    "plain",
                ]

        adapter = Listing(resources=[mcp_resource("memo://a", "a", mime_type="text/x-memo")])
        async with MCPRuntime() as runtime:
            await runtime.register_server(
                "fake", lambda: adapter, refresh=RefreshPolicy(on_register=True)
            )
            async with Client(runtime.as_mcp_server(mode="catalog")) as client:
                text, blob, plain = await client.read_resource("memo://a")
                assert isinstance(text, types.TextResourceContents)
                assert (text.text, text.mime_type) == ("text", "text/csv")
                assert isinstance(blob, types.BlobResourceContents)
                assert (base64.b64decode(blob.blob), blob.mime_type) == (b"\x00", "text/x-memo")
                assert isinstance(plain, types.TextResourceContents)
                assert (plain.text, plain.mime_type) == ("plain", "text/x-memo")

    async def test_first_registered_server_serves_a_shared_uri(self) -> None:
        first = FakeAdapter(resources=[mcp_resource("memo://shared", "first")])
        second = FakeAdapter(resources=[mcp_resource("memo://shared", "second")])
        async with MCPRuntime() as runtime:
            policy = RefreshPolicy(on_register=True)
            await runtime.register_server("b_first", lambda: first, refresh=policy)
            await runtime.register_server("a_second", lambda: second, refresh=policy)
            async with Client(runtime.as_mcp_server(mode="catalog")) as client:
                [listed] = await client.list_resources()
                assert listed.name == "first"
                await client.read_resource("memo://shared")
            assert first.calls[-1] == ("read_resource", "memo://shared")
            assert ("read_resource", "memo://shared") not in second.calls

    async def test_ambiguous_tool_names_are_unknown(self) -> None:
        async with MCPRuntime() as runtime:
            policy = RefreshPolicy(on_register=True)
            await runtime.register_server(
                "a", lambda: FakeAdapter(tools=[mcp_tool("b_c")]), refresh=policy
            )
            await runtime.register_server(
                "a_b", lambda: FakeAdapter(tools=[mcp_tool("c")]), refresh=policy
            )
            async with Client(runtime.as_mcp_server(mode="catalog")) as client:
                with pytest.raises(ToolError, match="Unknown tool"):
                    await client.call_tool("a_b_c", {})


class TestSearchMode:
    async def test_finds_and_calls_tools(self, runtime: MCPRuntime) -> None:
        async with Client(runtime.as_mcp_server(max_results=2)) as client:
            names = [tool.name for tool in await client.list_tools()]
            assert names == ["search_tools", "call_tool"]
            found = await client.call_tool("search_tools", {"query": "read a text file"})
            assert found.structured_content is not None
            matches = found.structured_content["result"]
            assert len(matches) <= 2
            assert matches[0]["name"] == "files_read_text_file"
            called = await client.call_tool(
                "call_tool",
                {"name": "files_read_text_file", "arguments": {"path": "a.txt"}},
            )
            assert called.content[0].text == "contents of a.txt"  # type: ignore[union-attr]
            direct = await client.call_tool("weather_get_forecast", {"city": "Oslo"})
            assert direct.structured_content == {"city": "Oslo", "temp": 21}

    async def test_finds_nothing_without_tools(self) -> None:
        async with MCPRuntime() as runtime, Client(runtime.as_mcp_server()) as client:
            found = await client.call_tool("search_tools", {"query": "anything"})
            assert found.structured_content == {"result": []}

    async def test_transform_accepts_search_options(self, runtime: MCPRuntime) -> None:
        transform = RouterSearchTransform(
            runtime, max_results=1, search_tool_name="find", always_visible=["demo_add"]
        )
        server = FastMCP("custom", providers=[RouterProvider(runtime)], transforms=[transform])
        async with Client(server) as client:
            names = [tool.name for tool in await client.list_tools()]
            assert names == ["demo_add", "find", "call_tool"]
            found = await client.call_tool("find", {"query": "weather forecast"})
            assert found.structured_content is not None
            assert [m["name"] for m in found.structured_content["result"]] == [
                "weather_get_forecast"
            ]


class TestCodeMode:
    async def test_needs_the_codemode_extra(
        self, runtime: MCPRuntime, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        find_spec = importlib.util.find_spec
        monkeypatch.setattr(
            importlib.util,
            "find_spec",
            lambda name, *args: None if name == "pydantic_monty" else find_spec(name, *args),
        )
        with pytest.raises(ConfigurationError, match=r"mcp-capability-router\[codemode\]"):
            runtime.as_mcp_server(mode="code")

    async def test_runs_code_that_calls_tools(self, runtime: MCPRuntime) -> None:
        async with Client(runtime.as_mcp_server(mode="code")) as client:
            names = [tool.name for tool in await client.list_tools()]
            assert names == ["search", "get_schema", "execute"]
            found = await client.call_tool("search", {"query": "weather forecast"})
            assert "weather_get_forecast" in found.content[0].text  # type: ignore[union-attr]
            code = "return await call_tool('weather_get_forecast', {'city': 'Rome'})"
            result = await client.call_tool("execute", {"code": code})
            assert "Rome" in result.content[0].text  # type: ignore[union-attr]


class TestServerOptions:
    async def test_passes_options_to_fastmcp(self, runtime: MCPRuntime) -> None:
        extra = FastMCP("extra")

        @extra.tool
        def ping() -> str:
            """Answer pong."""
            return "pong"

        server = runtime.as_mcp_server(
            "gateway",
            mode="catalog",
            instructions="Use the tools.",
            transforms=[Namespace("gw")],
            providers=[extra.providers[0]],
        )
        assert server.name == "gateway"
        assert server.instructions == "Use the tools."
        async with Client(server) as client:
            names = [tool.name for tool in await client.list_tools()]
            assert "gw_demo_add" in names
            assert "gw_ping" in names
            result = await client.call_tool("gw_demo_add", {"a": 1, "b": 2})
            assert result.data == 3

    async def test_provider_exposes_the_runtime(self, runtime: MCPRuntime) -> None:
        assert RouterProvider(runtime).runtime is runtime

    @pytest.mark.parametrize(
        ("options", "message"),
        [
            ({"mode": "everything"}, "mode must be"),
            ({"max_results": 0}, "max_results"),
        ],
    )
    async def test_rejects_invalid_options(self, options: dict[str, Any], message: str) -> None:
        async with MCPRuntime() as runtime:
            with pytest.raises(ConfigurationError, match=message):
                runtime.as_mcp_server(**options)

    async def test_needs_an_open_runtime(self) -> None:
        runtime = MCPRuntime()
        await runtime.close()
        with pytest.raises(RuntimeClosedError):
            runtime.as_mcp_server()


def test_describe_errors() -> None:
    plain = ValueError()
    assert _describe(plain) == "ValueError"
    noted = ValueError()
    noted.add_note("first")
    noted.add_note("second")
    assert _describe(noted) == "ValueError: first; second"
    assert _describe(ValueError("detail")) == "ValueError: detail"
