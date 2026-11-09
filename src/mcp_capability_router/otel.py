"""OpenTelemetry tracing of server operations.

This module requires the `otel` extra. It uses only the supplied tracer; provider
configuration and shutdown remain application-owned. For metrics, pass a
`refresh_engine.otel.OpenTelemetryMetricsSink` as the runtime's `metrics`.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer

from .contracts import CallNext, Interceptor, Operation, OperationContext
from .errors import ConfigurationError
from .models import Prompt, Resource, Tool

__all__ = ["OpenTelemetryInterceptor"]

_METHODS = {
    Operation.CONNECT: "initialize",
    Operation.DISCOVER: "discover",
    Operation.CALL_TOOL: "tools/call",
    Operation.READ_RESOURCE: "resources/read",
    Operation.GET_PROMPT: "prompts/get",
}


class OpenTelemetryInterceptor(Interceptor):
    """Records a client span for every server operation.

    Spans follow the OpenTelemetry semantic conventions for MCP: they are named
    after the MCP method and its target, as in `tools/call search_docs`, and carry
    `mcp.method.name`, `gen_ai.tool.name`, `gen_ai.prompt.name`, or
    `mcp.resource.uri`, along with `mcp_capability_router.server_id`. A failed
    operation sets the span status to error, records the exception, and sets
    `error.type`. Arguments and results are never recorded.

    Add it first among the runtime's interceptors so that its span covers the
    others; it covers every attempt of the operation.

    Example:
        ```python
        from opentelemetry import trace

        runtime = MCPRuntime(interceptors=[OpenTelemetryInterceptor(trace.get_tracer("my-agent"))])
        ```
    """

    def __init__(self, tracer: Tracer | None = None) -> None:
        """Create an interceptor that records spans with `tracer`.

        Args:
            tracer: The tracer; the global tracer provider's tracer for
                `mcp_capability_router` when `None`.

        Raises:
            ConfigurationError: If `tracer` is not an OpenTelemetry tracer.
        """
        if tracer is not None and not isinstance(tracer, Tracer):
            msg = f"tracer {tracer!r} is not an opentelemetry.trace.Tracer"
            raise ConfigurationError(msg)
        self._tracer = tracer if tracer is not None else trace.get_tracer("mcp_capability_router")

    async def __call__(self, context: OperationContext, call_next: CallNext, /) -> Any:
        """Run the operation inside a span."""
        method = _METHODS[context.operation]
        attributes: dict[str, str] = {
            "mcp.method.name": method,
            "mcp_capability_router.server_id": context.server_id,
            "mcp_capability_router.operation": str(context.operation),
        }
        target = context.server_id
        capability = context.capability
        if isinstance(capability, Tool):
            attributes["gen_ai.tool.name"] = capability.name
            attributes["gen_ai.operation.name"] = "execute_tool"
            target = capability.name
        elif isinstance(capability, Prompt):
            attributes["gen_ai.prompt.name"] = capability.name
            target = capability.name
        elif isinstance(capability, Resource):
            attributes["mcp.resource.uri"] = capability.uri
            target = capability.uri
        if capability is not None:
            attributes["mcp_capability_router.capability_id"] = capability.capability_id
        with self._tracer.start_as_current_span(
            f"{method} {target}",
            kind=SpanKind.CLIENT,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                return await call_next()
            except BaseException as error:
                span.set_attribute("error.type", type(error).__qualname__)
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, str(error) or None))
                raise
