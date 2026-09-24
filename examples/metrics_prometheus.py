"""Real MetricsHook plugin exposing Prometheus metrics from a running MCPRuntime.

This proves the third plugin point (after ``CapabilityRetriever`` in
``vector_retrieval_qdrant.py``/``embedding_ollama.py`` and ``CapabilityRegistry`` in
``postgres_registry.py``): observability. ``MCPRuntime(metrics=...)`` accepts anything
satisfying the ``MetricsHook`` protocol; the core package ships a no-op ``NullMetrics``,
and this example supplies a real ``PrometheusMetricsHook`` instead, with zero changes to
``MCPRuntime`` or the resilience pipeline. ``PrometheusMetricsHook`` subclasses the
optional ``MetricsHookBase`` abstract base class rather than the ``MetricsHook`` protocol
directly, so a future maintainer who forgets to implement ``record`` gets a loud
``TypeError`` at instantiation time instead of a silently-installed no-op hook.

Run:

    uv sync --extra examples
    uv run python -m examples.metrics_prometheus

This starts a Prometheus text-exposition HTTP server on ``:9105/metrics`` (configurable via
``METRICS_PORT``), drives some real traffic through the runtime (including retried and
permanently failing operations, to produce non-trivial counters), and then keeps the
server running for ``METRICS_SERVE_SECONDS`` seconds (default 120) so an external
Prometheus instance has time to scrape it -- see
``docs/guides/agent-integrations.md`` for the accompanying real Prometheus + Grafana
setup, verified against this exact script in this repository's development environment.
"""

from __future__ import annotations

import asyncio
import os

from prometheus_client import Counter, start_http_server
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

from mcp_capability_router import MCPRuntime
from mcp_capability_router.resilience import MetricsHookBase, semantic_classifier

METRICS_PORT = int(os.environ.get("METRICS_PORT", "9105"))
SERVE_SECONDS = float(os.environ.get("METRICS_SERVE_SECONDS", "120"))

_OPERATIONS_TOTAL = Counter(
    "mcp_router_operations_total",
    "Total MCP operations run through the resilience pipeline",
    ["server_id", "operation", "outcome"],
)


class PrometheusMetricsHook(MetricsHookBase):
    """Adapts the runtime's ``MetricsHook`` protocol to real Prometheus counters."""

    async def record(self, event: str, *, attributes=None) -> None:
        attributes = attributes or {}
        if event not in ("operation.success", "operation.failure"):
            return
        outcome = "success" if event == "operation.success" else "failure"
        _OPERATIONS_TOTAL.labels(
            server_id=str(attributes.get("server_id", "unknown")),
            operation=str(attributes.get("operation", "unknown")),
            outcome=outcome,
        ).inc()


class FlakyAdapter:
    def __init__(self) -> None:
        self.attempts = 0

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "flaky_call", "description": "sometimes fails"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        self.attempts += 1
        if self.attempts % 3 == 0:
            raise TimeoutError("transient upstream failure")
        return {"attempts": self.attempts}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


class AlwaysFailingAdapter:
    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "broken_call", "description": "always fails"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        raise ConnectionError("backend permanently down")

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def generate_traffic(runtime: MCPRuntime) -> None:
    flaky_capability = (await runtime.retrieve("flaky_call"))[0]
    for _ in range(15):
        try:
            await runtime.execute(flaky_capability.capability_id)
        except Exception:
            pass

    broken_capability = (await runtime.retrieve("broken_call"))[0]
    for _ in range(5):
        try:
            await runtime.execute(broken_capability.capability_id)
        except Exception:
            pass


async def main() -> None:
    start_http_server(METRICS_PORT)
    print(f"Prometheus metrics exposed at http://0.0.0.0:{METRICS_PORT}/metrics")

    hook = PrometheusMetricsHook()
    retry = AsyncRetrying(
        stop=stop_after_attempt(2),
        retry=retry_if_exception(semantic_classifier),
        reraise=True,
    )
    async with MCPRuntime(retry=retry, metrics=hook) as runtime:
        await runtime.register_server("flaky", lambda: FlakyAdapter())
        await runtime.register_server("broken", lambda: AlwaysFailingAdapter())
        await runtime.refresh_server("flaky")
        await runtime.refresh_server("broken")

        await generate_traffic(runtime)
        print("generated real traffic; sample of exposed counters:")
        for metric in _OPERATIONS_TOTAL.collect():
            for sample in metric.samples:
                print(" ", sample.name, sample.labels, sample.value)

        print(f"serving /metrics for {SERVE_SECONDS:.0f}s for an external scraper...")
        await asyncio.sleep(SERVE_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
