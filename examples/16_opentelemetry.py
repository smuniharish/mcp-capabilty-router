"""Trace server operations and export refresh metrics with OpenTelemetry.

`OpenTelemetryInterceptor` records a client span for every MCP operation, named
and attributed after the OpenTelemetry semantic conventions for MCP, and
refresh-engine's `OpenTelemetryMetricsSink` turns refresh metrics into
OpenTelemetry instruments. Providers stay application-owned.

By default the spans and metrics are collected in memory and printed. Set
`OTEL_EXPORTER_OTLP_ENDPOINT` (for example `http://localhost:4317`) to export them
over OTLP to a collector, Jaeger, or any compatible backend instead.

Requires the `otel` extra: `pip install "mcp-capability-router[otel]"`.
"""

import asyncio
import os

from common import crm_server
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from refresh_engine.otel import OpenTelemetryMetricsSink

from mcp_capability_router import MCPRuntime, RefreshPolicy
from mcp_capability_router.otel import OpenTelemetryInterceptor


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

    tracer = tracer_provider.get_tracer("mcp-capability-router-example")
    runtime = MCPRuntime(
        interceptors=[OpenTelemetryInterceptor(tracer)],
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

    for span in spans.get_finished_spans():
        print(f"span {span.name!r} {dict(span.attributes or {})}")
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
