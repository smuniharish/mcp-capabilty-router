from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ToolCallRequest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as lc_tool

from mcp_capability_router import (
    CapabilityRoutingMiddleware,
    ConfigurationError,
    MCPRuntime,
    RefreshPolicy,
    ServerConnectionError,
)
from mcp_capability_router._internal.tools import capability_tool
from mcp_capability_router.agents import _latest_user_text
from tests.support import (
    FakeAdapter,
    ScriptedChatModel,
    mcp_tool,
    tool,
    tool_messages,
)

SEARCH_SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}


def crm() -> FakeAdapter:
    return FakeAdapter(
        tools=[
            mcp_tool("search", "Search customer records", input_schema=SEARCH_SCHEMA),
            mcp_tool("delete", "Delete a customer record"),
        ]
    )


def billing() -> FakeAdapter:
    return FakeAdapter(
        tools=[mcp_tool("search", "Search invoices", input_schema=SEARCH_SCHEMA)]
    )


@pytest.fixture
async def runtime() -> AsyncIterator[MCPRuntime]:
    async with MCPRuntime() as instance:
        policy = RefreshPolicy(on_register=True)
        await instance.register_server("crm", crm, refresh=policy)
        await instance.register_server("billing", billing, refresh=policy)
        yield instance


def tool_call(
    name: str, args: dict[str, Any], call_id: str = "call-1"
) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class TestCapabilityTool:
    async def test_returns_content_and_artifact_of_tool_messages(self) -> None:
        class Runtime:
            async def execute(
                self, capability_id: str, arguments: dict[str, Any]
            ) -> Any:
                return ToolMessage(
                    content="42", artifact={"structured_content": 42}, tool_call_id="x"
                )

        routed = capability_tool(Runtime(), tool("s", "answer", "Answer"))  # type: ignore[arg-type]
        message = await routed.ainvoke(tool_call("answer", {}))
        assert (message.content, message.artifact) == ("42", {"structured_content": 42})

    async def test_reports_router_errors_to_the_model(
        self, runtime: MCPRuntime
    ) -> None:
        adapter = await runtime._servers["crm"].handle.adapter()
        adapter.failures["call_tool"] = [ServerConnectionError("crm is down")]  # type: ignore[attr-defined]
        routed = await runtime.as_tool("crm:tool:search")
        message = await routed.ainvoke(tool_call("search", {"q": "acme"}))
        assert message.status == "error"
        assert message.content == "ServerConnectionError: crm is down"

    async def test_passes_arguments_named_like_langchain_parameters(self) -> None:
        received: list[dict[str, Any]] = []

        class Runtime:
            async def execute(
                self, capability_id: str, arguments: dict[str, Any]
            ) -> Any:
                received.append(arguments)
                return "ok"

        schema = {
            "type": "object",
            "properties": {
                name: {"type": "string"}
                for name in ("config", "run_manager", "callbacks", "q")
            },
        }
        routed = capability_tool(
            Runtime(),  # type: ignore[arg-type]
            tool("s", "apply", "Apply", input_schema=schema),
        )
        arguments = {"config": "c", "run_manager": "r", "callbacks": "b", "q": "x"}
        message = await routed.ainvoke(tool_call("apply", arguments))
        assert message.content == "ok"
        assert received == [arguments]

    @pytest.mark.parametrize(
        ("note", "content"),
        [
            (
                "call_tool on server 's' exceeded the operation timeout of 1s",
                "TimeoutError: call_tool on server 's' exceeded the operation "
                "timeout of 1s",
            ),
            (None, "TimeoutError"),
        ],
    )
    async def test_reports_timeouts_to_the_model(
        self, note: str | None, content: str
    ) -> None:
        class Runtime:
            async def execute(
                self, capability_id: str, arguments: dict[str, Any]
            ) -> Any:
                error = TimeoutError()
                if note is not None:
                    error.add_note(note)
                raise error

        routed = capability_tool(Runtime(), tool("s", "slow", "Slow"))  # type: ignore[arg-type]
        message = await routed.ainvoke(tool_call("slow", {}))
        assert message.status == "error"
        assert message.content == content

    async def test_plain_results_and_fallback_descriptions(
        self, runtime: MCPRuntime
    ) -> None:
        routed = await runtime.as_tool("crm:tool:search")
        message = await routed.ainvoke(tool_call("search", {"q": "acme"}))
        assert message.content == '{"tool": "search", "arguments": {"q": "acme"}}'
        assert message.artifact is None
        untitled = capability_tool(runtime, tool("crm", "x"))
        assert untitled.description == "x"
        titled = capability_tool(runtime, tool("crm", "x", title="X tool"))
        assert titled.description == "X tool"


class TestLatestUserText:
    def test_reads_the_latest_human_message(self) -> None:
        assert _latest_user_text([]) == ""
        assert _latest_user_text([AIMessage("only the model")]) == ""
        assert (
            _latest_user_text(
                [HumanMessage("old"), AIMessage("reply"), HumanMessage("new question")]
            )
            == "new question"
        )
        blocks = HumanMessage(
            content=[
                {"type": "text", "text": "find"},
                "invoices",
                {"type": "image", "url": "https://example.com/x.png"},
            ]
        )
        assert _latest_user_text([blocks]) == "find invoices"


class TestMiddleware:
    @pytest.mark.parametrize(
        ("options", "message"),
        [({"limit": 0}, "limit"), ({"server_id": "bad id"}, "invalid server ID")],
    )
    def test_rejects_invalid_options(
        self, runtime: MCPRuntime, options: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ConfigurationError, match=message):
            CapabilityRoutingMiddleware(runtime, **options)

    async def test_routes_only_relevant_tools_with_qualified_names(
        self, runtime: MCPRuntime
    ) -> None:
        model = ScriptedChatModel(
            responses=[
                AIMessage(
                    content="", tool_calls=[tool_call("crm_search", {"q": "acme"})]
                ),
                AIMessage(content="Found acme."),
            ]
        )
        agent = create_agent(
            model, tools=[], middleware=[CapabilityRoutingMiddleware(runtime, limit=2)]
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage("search the customer records for acme")]}
        )
        assert model.calls[0] == ["crm_search", "billing_search"]
        [message] = tool_messages(result)
        assert message.content == '{"tool": "search", "arguments": {"q": "acme"}}'
        assert result["messages"][-1].content == "Found acme."

    async def test_scoped_middleware_uses_plain_names_and_keeps_static_tools(
        self, runtime: MCPRuntime
    ) -> None:
        @lc_tool
        def search(q: str) -> str:
            """Search the web."""
            return q

        model = ScriptedChatModel(
            responses=[
                AIMessage(content="", tool_calls=[tool_call("delete", {})]),
                AIMessage(content="Deleted."),
            ]
        )
        agent = create_agent(
            model,
            tools=[search],
            middleware=[CapabilityRoutingMiddleware(runtime, server_id="crm")],
        )
        result = await agent.ainvoke({"messages": [HumanMessage("search and delete")]})
        assert model.calls[0] == ["search", "delete"]
        [message] = tool_messages(result)
        assert message.content == '{"tool": "delete", "arguments": {}}'

    async def test_passes_through_requests_without_a_query_or_routed_tool(
        self, runtime: MCPRuntime
    ) -> None:
        middleware = CapabilityRoutingMiddleware(runtime)
        model = ScriptedChatModel(responses=[])
        request = ModelRequest(
            model=model,
            messages=[AIMessage("no user message")],
            tools=[],
            state={"messages": []},
            runtime=None,
        )
        seen: list[ModelRequest[Any]] = []

        async def handler(forwarded: ModelRequest[Any]) -> Any:
            seen.append(forwarded)
            return "response"

        assert await middleware.awrap_model_call(request, handler) == "response"
        assert seen == [request]
        unmatched = ModelRequest(
            model=model,
            messages=[HumanMessage("nothing here matches")],
            tools=[],
            state={"messages": []},
            runtime=None,
        )
        assert await middleware.awrap_model_call(unmatched, handler) == "response"
        assert seen[-1] is unmatched

        @lc_tool
        def static(value: str) -> str:
            """Return the value."""
            return value

        calls: list[ToolCallRequest] = []

        async def run(forwarded: ToolCallRequest) -> ToolMessage:
            calls.append(forwarded)
            return ToolMessage(content="ran", tool_call_id="call-1")

        known = ToolCallRequest(
            tool_call=tool_call("static", {"value": "x"}),  # type: ignore[arg-type]
            tool=static,
            state={},
            runtime=None,  # type: ignore[arg-type]
        )
        await middleware.awrap_tool_call(known, run)
        unknown = ToolCallRequest(
            tool_call=tool_call("crm_unknown", {}),  # type: ignore[arg-type]
            tool=None,
            state={},
            runtime=None,  # type: ignore[arg-type]
        )
        await middleware.awrap_tool_call(unknown, run)
        assert [call.tool for call in calls] == [static, None]

    async def test_reports_ambiguous_tool_names(self) -> None:
        async with MCPRuntime() as runtime:
            policy = RefreshPolicy(on_register=True)
            await runtime.register_server(
                "a", lambda: FakeAdapter(tools=[mcp_tool("b_x")]), refresh=policy
            )
            await runtime.register_server(
                "a_b", lambda: FakeAdapter(tools=[mcp_tool("x")]), refresh=policy
            )
            middleware = CapabilityRoutingMiddleware(runtime)
            request = ToolCallRequest(
                tool_call=tool_call("a_b_x", {}),  # type: ignore[arg-type]
                tool=None,
                state={},
                runtime=None,  # type: ignore[arg-type]
            )

            async def run(forwarded: ToolCallRequest) -> ToolMessage:
                raise AssertionError("must not run")

            message = await middleware.awrap_tool_call(request, run)
            assert isinstance(message, ToolMessage)
            assert message.status == "error"
            assert "ambiguous between servers: a, a_b" in str(message.content)
