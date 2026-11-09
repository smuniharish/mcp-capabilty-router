from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from mcp_capability_router import (
    ConfigurationError,
    MCPRuntime,
    RefreshPolicy,
    ToolExecutionError,
)
from mcp_capability_router.otel import OpenTelemetryInterceptor
from tests.support import FakeAdapter, mcp_prompt, mcp_resource, mcp_tool

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def exporter() -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    yield exporter
    exporter.clear()


def interceptor(exporter: InMemorySpanExporter) -> OpenTelemetryInterceptor:
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OpenTelemetryInterceptor(provider.get_tracer("tests"))


def adapter() -> FakeAdapter:
    return FakeAdapter(
        tools=[mcp_tool("search", "Search records")],
        resources=[mcp_resource("file:///guide.md", "guide")],
        prompts=[mcp_prompt("summarize")],
    )


async def test_spans_follow_the_mcp_semantic_conventions(
    exporter: InMemorySpanExporter,
) -> None:
    async with MCPRuntime(interceptors=[interceptor(exporter)]) as runtime:
        await runtime.register_server("crm", adapter, refresh=RefreshPolicy(on_register=True))
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
    async with MCPRuntime(interceptors=[interceptor(exporter)]) as runtime:
        await runtime.register_server(
            "crm", lambda: failing, refresh=RefreshPolicy(on_register=True)
        )
        with pytest.raises(ToolExecutionError):
            await runtime.execute("crm:tool:search")
    span = next(s for s in exporter.get_finished_spans() if s.name == "tools/call search")
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "bad input"
    assert (span.attributes or {})["error.type"] == "ToolExecutionError"
    assert [event.name for event in span.events] == ["exception"]


def test_tracers_are_validated() -> None:
    assert isinstance(OpenTelemetryInterceptor(), OpenTelemetryInterceptor)
    with pytest.raises(ConfigurationError, match="Tracer"):
        OpenTelemetryInterceptor(object())  # type: ignore[arg-type]
