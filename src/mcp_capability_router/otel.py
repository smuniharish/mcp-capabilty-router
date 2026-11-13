"""OpenTelemetry tracing of server operations.

The runtime traces every server operation by default, through the
`OpenTelemetryInterceptor` that it adds for its `tracing` mode. Tracing uses only
the OpenTelemetry API, so it records nothing until the application configures an
OpenTelemetry SDK; provider configuration and shutdown remain application-owned.
For metrics, pass a `refresh_engine.otel.OpenTelemetryMetricsSink` (the `otel`
extra) as the runtime's `metrics`.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode, Tracer, TracerProvider
from pydantic import TypeAdapter

from ._internal.version import VERSION
from .contracts import CallNext, Interceptor, Operation, OperationContext
from .errors import ConfigurationError
from .models import Prompt, Resource, Tool

__all__ = ["INSTRUMENTATION_NAME", "OpenTelemetryInterceptor", "TracingMode"]

INSTRUMENTATION_NAME = "mcp_capability_router"
"""The instrumentation scope of the router's spans."""

logger = logging.getLogger("mcp_capability_router")

type TracingMode = Literal["router", "fastmcp", "all", "off"]
"""Which spans the runtime's server operations record.

- `"router"`: one router span per operation, such as `tools/call search_docs`.
  FastMCP's own spans within the operation are suppressed, so the trace has no
  duplicates; this includes the server spans of in-process servers.
- `"fastmcp"`: FastMCP's own spans only, as without the router.
- `"all"`: the router span with FastMCP's spans nested in it, for debugging.
- `"off"`: neither router nor FastMCP spans.

In every mode the trace context is propagated to servers, so the spans that a
remote server records nest under the operation. The MCP SDK's transport spans
(`MCP send ...`) and the spans of the gateway's incoming requests are recorded
as configured by the MCP SDK and FastMCP.
"""

_METHODS = {
    Operation.CONNECT: "initialize",
    Operation.DISCOVER: "discover",
    Operation.CALL_TOOL: "tools/call",
    Operation.READ_RESOURCE: "resources/read",
    Operation.GET_PROMPT: "prompts/get",
}
_JSON_ADAPTER = TypeAdapter(Any)


def _record_content(span: trace.Span, attribute: str, value: Any) -> None:
    try:
        content = _JSON_ADAPTER.dump_json(value, by_alias=True).decode("utf-8")
    except (TypeError, ValueError, RecursionError, OverflowError):
        logger.warning("Could not serialize tool content for span attribute %s", attribute)
    else:
        span.set_attribute(attribute, content)


class OpenTelemetryInterceptor(Interceptor):
    """Records a client span for every server operation.

    Spans follow the OpenTelemetry semantic conventions for MCP: they are named
    after the MCP method and its target, as in `tools/call search_docs`, and carry
    `mcp.method.name`, `gen_ai.tool.name`, `gen_ai.prompt.name`, or
    `mcp.resource.uri`, along with `mcp_capability_router.server_id`. A failed
    operation sets the span status to error, records the exception, and sets
    `error.type`. Tool arguments and results are recorded as JSON by default;
    they can contain sensitive data. Disable capture with `capture_tool_content=False`.

    The runtime adds one as its outermost interceptor in the `"router"` and
    `"all"` tracing modes, so its span covers the other interceptors and every
    attempt of the operation. Pass one among the runtime's `interceptors` to
    choose its tracer or its position instead; the runtime then adds none.

    Example:
        ```python
        from opentelemetry import trace

        runtime = MCPRuntime(interceptors=[OpenTelemetryInterceptor(trace.get_tracer("my-agent"))])
        ```
    """

    def __init__(
        self,
        tracer: Tracer | None = None,
        *,
        tracer_provider: TracerProvider | None = None,
        capture_tool_content: bool = True,
    ) -> None:
        """Create an interceptor that records spans with `tracer`.

        Args:
            tracer: The tracer; the `mcp_capability_router` tracer of
                `tracer_provider` when `None`.
            tracer_provider: The provider of the default tracer; the global
                tracer provider when `None`. Ignored when `tracer` is given.
            capture_tool_content: Record tool arguments and results in span
                attributes. Disable this to avoid exporting tool content.

        Raises:
            ConfigurationError: If `tracer` is not an OpenTelemetry tracer or
                `tracer_provider` is not an OpenTelemetry tracer provider.
        """
        if tracer is not None and not isinstance(tracer, Tracer):
            msg = f"tracer {tracer!r} is not an opentelemetry.trace.Tracer"
            raise ConfigurationError(msg)
        if tracer_provider is not None and not isinstance(tracer_provider, TracerProvider):
            msg = (
                f"tracer_provider {tracer_provider!r} is not an opentelemetry.trace.TracerProvider"
            )
            raise ConfigurationError(msg)
        if not isinstance(capture_tool_content, bool):
            msg = "capture_tool_content must be a bool"
            raise ConfigurationError(msg)
        self._capture_tool_content = capture_tool_content
        self._tracer = (
            tracer
            if tracer is not None
            else trace.get_tracer(INSTRUMENTATION_NAME, VERSION, tracer_provider)
        )

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
            capture = (
                self._capture_tool_content
                and context.operation is Operation.CALL_TOOL
                and span.is_recording()
            )
            if capture:
                _record_content(span, "gen_ai.tool.call.arguments", context.arguments)
            try:
                result = await call_next()
            except BaseException as error:
                span.set_attribute("error.type", type(error).__qualname__)
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, str(error) or None))
                raise
            if capture:
                _record_content(span, "gen_ai.tool.call.result", result)
            return result
