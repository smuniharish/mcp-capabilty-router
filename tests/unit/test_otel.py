from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp import Client, FastMCP
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from mcp_capability_router import (
    ConfigurationError,
    MCPRuntime,
    RefreshPolicy,
    ToolExecutionError,
    TracingMode,
)
from mcp_capability_router.otel import INSTRUMENTATION_NAME, OpenTelemetryInterceptor
from tests.support import FakeAdapter, mcp_prompt, mcp_resource, mcp_tool

if TYPE_CHECKING:
    from collections.abc import Iterator

ON_REGISTER = RefreshPolicy(on_register=True)


def traced(exporter: InMemorySpanExporter) -> TracerProvider:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    yield exporter
    exporter.clear()


@pytest.fixture(scope="module")
def global_spans() -> InMemorySpanExporter:
    """Spans of the global tracer provider, which FastMCP and the MCP SDK use."""
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def spans(global_spans: InMemorySpanExporter) -> Iterator[InMemorySpanExporter]:
    global_spans.clear()
    yield global_spans
    global_spans.clear()


def adapter() -> FakeAdapter:
    return FakeAdapter(
        tools=[mcp_tool("search", "Search records")],
        resources=[mcp_resource("file:///guide.md", "guide")],
        prompts=[mcp_prompt("summarize")],
    )


def lookup_server(trace_ids: list[int]) -> FastMCP:
    server = FastMCP("crm")

    @server.tool
    def lookup(query: str) -> str:
        """Look up a record."""
        trace_ids.append(trace.get_current_span().get_span_context().trace_id)
        return query

    return server


def scopes(exporter: InMemorySpanExporter, name: str) -> list[tuple[str, SpanKind]]:
    return sorted(
        (
            (span.instrumentation_scope.name if span.instrumentation_scope else "", span.kind)
            for span in exporter.get_finished_spans()
            if span.name == name
        ),
        key=lambda scope: (scope[0], scope[1].name),
    )


async def test_operations_are_traced_by_default(exporter: InMemorySpanExporter) -> None:
    async with MCPRuntime(tracer_provider=traced(exporter)) as runtime:
        await runtime.register_server("crm", adapter, refresh=ON_REGISTER)
        await runtime.connect("crm")
        await runtime.execute("crm:tool:search", {"q": "secret"})
        await runtime.read_resource("crm:resource:file:///guide.md")
        await runtime.get_prompt("crm:prompt:summarize")
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {
        "initialize crm",
        "discover crm",
        "tools/call search",
        "resources/read file:///guide.md",
        "prompts/get summarize",
    }
    call = spans["tools/call search"]
    assert call.kind is SpanKind.CLIENT
    assert call.instrumentation_scope is not None
    assert call.instrumentation_scope.name == INSTRUMENTATION_NAME
    assert dict(call.attributes or {}) == {
        "mcp.method.name": "tools/call",
        "mcp_capability_router.server_id": "crm",
        "mcp_capability_router.operation": "call_tool",
        "gen_ai.tool.name": "search",
        "gen_ai.operation.name": "execute_tool",
        "mcp_capability_router.capability_id": "crm:tool:search",
    }
    attributes = spans["resources/read file:///guide.md"].attributes or {}
    assert attributes["mcp.resource.uri"] == "file:///guide.md"
    assert (spans["prompts/get summarize"].attributes or {})["gen_ai.prompt.name"] == "summarize"


async def test_failures_are_recorded(exporter: InMemorySpanExporter) -> None:
    failing = adapter()
    failing.failures["call_tool"] = [ToolExecutionError("bad input")]
    async with MCPRuntime(tracer_provider=traced(exporter)) as runtime:
        await runtime.register_server("crm", lambda: failing, refresh=ON_REGISTER)
        with pytest.raises(ToolExecutionError):
            await runtime.execute("crm:tool:search")
    span = next(s for s in exporter.get_finished_spans() if s.name == "tools/call search")
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "bad input"
    assert (span.attributes or {})["error.type"] == "ToolExecutionError"
    assert [event.name for event in span.events] == ["exception"]


async def test_an_explicit_interceptor_replaces_the_default(
    exporter: InMemorySpanExporter,
) -> None:
    default = InMemorySpanExporter()
    explicit = OpenTelemetryInterceptor(traced(exporter).get_tracer("my-agent"))
    async with MCPRuntime(interceptors=[explicit], tracer_provider=traced(default)) as runtime:
        await runtime.register_server("crm", adapter, refresh=ON_REGISTER)
        await runtime.execute("crm:tool:search")
    assert [span.name for span in exporter.get_finished_spans()] == [
        "discover crm",
        "tools/call search",
    ]
    assert default.get_finished_spans() == ()


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("router", [(INSTRUMENTATION_NAME, SpanKind.CLIENT)]),
        ("fastmcp", [("fastmcp", SpanKind.CLIENT), ("fastmcp", SpanKind.SERVER)]),
        (
            "all",
            [
                ("fastmcp", SpanKind.CLIENT),
                ("fastmcp", SpanKind.SERVER),
                (INSTRUMENTATION_NAME, SpanKind.CLIENT),
            ],
        ),
        ("off", []),
    ],
)
async def test_tracing_modes_choose_the_operation_spans(
    spans: InMemorySpanExporter,
    mode: TracingMode,
    expected: list[tuple[str, SpanKind]],
) -> None:
    trace_ids: list[int] = []
    async with MCPRuntime(tracing=mode) as runtime:
        await runtime.register_mcp("crm", lookup_server(trace_ids), refresh=ON_REGISTER)
        await runtime.execute("crm:tool:lookup", {"query": "acme"})
    assert scopes(spans, "tools/call lookup") == expected
    # The MCP SDK's transport span is recorded in every mode.
    assert scopes(spans, "MCP send tools/call lookup") == [("mcp-python-sdk", SpanKind.CLIENT)]
    [transport] = [s for s in spans.get_finished_spans() if s.name == "MCP send tools/call lookup"]
    assert transport.context is not None
    assert trace_ids == [transport.context.trace_id]


async def test_the_router_span_parents_the_transport_and_the_server(
    spans: InMemorySpanExporter,
) -> None:
    trace_ids: list[int] = []
    async with MCPRuntime() as runtime:
        await runtime.register_mcp("crm", lookup_server(trace_ids), refresh=ON_REGISTER)
        await runtime.execute("crm:tool:lookup", {"query": "acme"})
    finished = {span.name: span for span in spans.get_finished_spans()}
    router, transport = finished["tools/call lookup"], finished["MCP send tools/call lookup"]
    assert router.context is not None
    assert transport.parent is not None
    assert transport.parent.span_id == router.context.span_id
    assert trace_ids == [router.context.trace_id]


async def test_the_gateway_keeps_its_server_spans(spans: InMemorySpanExporter) -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_mcp("crm", lookup_server([]), refresh=ON_REGISTER)
        spans.clear()
        async with Client(runtime.as_mcp_server(mode="catalog")) as client:
            await client.call_tool("crm_lookup", {"query": "acme"})
    assert scopes(spans, "tools/call crm_lookup") == [
        ("fastmcp", SpanKind.CLIENT),
        ("fastmcp", SpanKind.SERVER),
    ]
    assert scopes(spans, "tools/call lookup") == [(INSTRUMENTATION_NAME, SpanKind.CLIENT)]


def test_tracing_options_are_validated() -> None:
    assert isinstance(OpenTelemetryInterceptor(), OpenTelemetryInterceptor)
    with pytest.raises(ConfigurationError, match="Tracer"):
        OpenTelemetryInterceptor(object())  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="TracerProvider"):
        MCPRuntime(tracer_provider=object())  # type: ignore[arg-type]
    with pytest.raises(ConfigurationError, match="tracing must be one of"):
        MCPRuntime(tracing="verbose")  # type: ignore[arg-type]
