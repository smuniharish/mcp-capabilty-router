"""Trace server operations and export refresh metrics with OpenTelemetry.

The runtime traces every MCP operation by default: one client span per
operation, named and attributed after the OpenTelemetry semantic conventions for
MCP. FastMCP's own spans for the same requests are suppressed, so a trace shows
each operation once, with the MCP SDK's transport span (`MCP send ...`) inside
it. Pass `tracing="all"` to see FastMCP's spans too, `"fastmcp"` to keep only
FastMCP's, or `"off"` to record neither. refresh-engine's
`OpenTelemetryMetricsSink` turns refresh metrics into OpenTelemetry instruments.
Providers stay application-owned.

By default the spans and metrics are collected in memory and printed as a tree.
Set `OTEL_EXPORTER_OTLP_ENDPOINT` (for example `http://localhost:4317`) to export
them over OTLP to a collector, Jaeger, Tempo, Langfuse, or any compatible backend
instead.

Requires the `otel` extra: `pip install "mcp-capability-router[otel]"`.
"""

import asyncio
import os

from common import crm_server
from opentelemetry import trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from refresh_engine.otel import OpenTelemetryMetricsSink

from mcp_capability_router import MCPRuntime, RefreshPolicy


def print_tree(spans: tuple[ReadableSpan, ...]) -> None:
    ids = {span.context.span_id for span in spans if span.context}
    children: dict[int | None, list[ReadableSpan]] = {}
    for span in spans:
        parent = span.parent.span_id if span.parent and span.parent.span_id in ids else None
        children.setdefault(parent, []).append(span)

    def show(parent: int | None, depth: int) -> None:
        for span in sorted(children.get(parent, []), key=lambda span: span.start_time or 0):
            scope = span.instrumentation_scope.name if span.instrumentation_scope else ""
            print(f"{'  ' * depth}{span.name} [{span.kind.name.lower()}, {scope}]")
            if span.context:
                show(span.context.span_id, depth + 1)

    show(None, 0)


async def main() -> None:
    resource = Resource.create({"service.name": "mcp-capability-router-example"})
    exporting = bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
    spans = InMemorySpanExporter()
    metrics = InMemoryMetricReader()
    tracer_provider = TracerProvider(resource=resource)
    if exporting:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())]
        )
    else:
        tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
        meter_provider = MeterProvider(resource=resource, metric_readers=[metrics])
    # The global provider also receives the spans of FastMCP and the MCP SDK.
    trace.set_tracer_provider(tracer_provider)

    runtime = MCPRuntime(
        metrics=OpenTelemetryMetricsSink(meter_provider.get_meter("refresh-engine")),
    )
    async with runtime:
        await runtime.register_mcp("crm", crm_server(), refresh=RefreshPolicy(on_register=True))
        await runtime.connect("crm")
        await runtime.execute("crm:tool:search_customers", {"query": "ada"})
        await runtime.read_resource("crm:resource:crm://schema/customer")

    if exporting:
        tracer_provider.shutdown()
        meter_provider.shutdown()
        print("exported spans and metrics over OTLP")
        return

    finished = spans.get_finished_spans()
    print_tree(finished)
    call = next(span for span in finished if span.name == "tools/call search_customers")
    print(f"attributes of {call.name!r}: {dict(call.attributes or {})}")
    data = metrics.get_metrics_data()
    names = sorted(
        {
            metric.name
            for resource_metrics in (data.resource_metrics if data else [])
            for scope in resource_metrics.scope_metrics
            for metric in scope.metrics
        }
    )
    print(f"metrics: {names}")
    tracer_provider.shutdown()
    meter_provider.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
