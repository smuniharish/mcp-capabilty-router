"""Rich MetricsHook plugin, driven by a real LLM agent instead of only fake adapters.

``metrics_prometheus.py`` proves the ``MetricsHook`` protocol is swappable for a real
``prometheus_client`` exporter, using two fake adapters and a flat operations counter.
This example goes further in two directions at once:

1. It drives the traffic with a *real* ``langchain.agents.create_agent`` LLM agent
   talking to a real Filesystem MCP server, so the metrics reflect genuine LLM
   tool-selection and tool-execution traffic, not scripted calls. A second,
   permanently-broken fake adapter is still registered alongside it so the exported
   counters also contain a non-trivial, contrasting failure/health signal --
   deliberately asking an LLM to "please fail" is unreliable, so that half stays
   scripted while the successful path is 100% real-LLM-driven.
2. It exports metrics developers actually reach for in production, not just a raw
   success/failure counter: per-operation latency, aggregated per-server health (from
   ``MCPRuntime.health()``), and -- via :meth:`ObservabilityMetricsHook.record_discovery`,
   called by application code right after each ``refresh_server()``, since
   ``refresh_engine.RefreshResult`` is not part of the ``MetricsHook`` event stream --
   how many tools/resources/prompts are currently discovered per server, and how many
   were added/modified/deleted by the most recent refresh.

Run:
    uv sync --extra mcp --extra agents --extra openai --extra examples
    uv run python -m examples.metrics_prometheus_real_llm

This starts a Prometheus text-exposition HTTP server on ``:9105/metrics`` (configurable via
``METRICS_PORT``), needs ``EXPLABS_API_KEY`` (and optionally ``EXPLABS_BASE_URL``/
``EXPLABS_MODEL``) in ``.env``, and Node.js/``npx`` on PATH for the real Filesystem MCP
server. See ``docs/guides/agent-integrations.md`` for the accompanying real Podman-hosted
Prometheus + Grafana setup, verified against this exact script in this repository's
development environment.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from prometheus_client import Counter, Gauge, Histogram, start_http_server
from refresh_engine import RefreshResult

from mcp_capability_router import MCPRuntime
from mcp_capability_router.models import CapabilityType
from mcp_capability_router.resilience import HealthState, MetricsHookBase

METRICS_PORT = int(os.environ.get("METRICS_PORT", "9105"))
SERVE_SECONDS = float(os.environ.get("METRICS_SERVE_SECONDS", "120"))

_OPERATIONS_TOTAL = Counter(
    "mcp_router_operations_total",
    "Total MCP operations run through the resilience pipeline",
    ["server_id", "operation", "outcome"],
)
_OPERATION_DURATION = Histogram(
    "mcp_router_operation_duration_seconds",
    "Wall-clock duration of each MCP operation run through the resilience pipeline",
    ["server_id", "operation"],
)
_RETRIES_TOTAL = Counter(
    "mcp_router_retries_total",
    "tenacity retry attempts made before an operation's outcome was recorded",
    ["outcome"],
)
_SERVER_HEALTH = Gauge(
    "mcp_router_server_health",
    "Aggregated per-server health from MCPRuntime.health() "
    "(3=healthy, 2=recovering, 1=degraded, 0=unhealthy)",
    ["server_id"],
)
_CAPABILITIES_DISCOVERED = Gauge(
    "mcp_router_capabilities_discovered",
    "Capabilities currently held in the registry for a server, broken down by type",
    ["server_id", "type"],
)
_REFRESH_LAST_RESULT = Gauge(
    "mcp_router_refresh_last_result",
    "Per-server capability counts from that server's most recent refresh_engine.RefreshResult",
    ["server_id", "field"],
)

_HEALTH_SCORE: Mapping[HealthState, int] = {
    HealthState.UNHEALTHY: 0,
    HealthState.DEGRADED: 1,
    HealthState.RECOVERING: 2,
    HealthState.HEALTHY: 3,
}


class ObservabilityMetricsHook(MetricsHookBase):
    """Adapts the runtime's ``MetricsHook`` protocol to production-shaped metrics.

    Subclasses the optional ``MetricsHookBase`` abstract base class (rather than the
    ``MetricsHook`` protocol directly) so that ``record`` is enforced: a subclass that
    forgets to implement it fails at instantiation time instead of silently no-op-ing.

    ``record()`` is called automatically by the resilience pipeline for every
    operation/retry event and covers latency, throughput, and health. Capability
    discovery/refresh metrics are *not* derivable from that event stream alone (the
    pipeline only ever emits ``server_id``/``operation`` attributes, never a
    ``RefreshResult``), so :meth:`record_discovery` is called explicitly by application
    code right after each ``runtime.refresh_server(...)``.
    """

    def __init__(self) -> None:
        # Set by application code once the MCPRuntime exists, so operation.success/
        # .failure events can look up aggregated server health via runtime.health().
        self.runtime: MCPRuntime | None = None
        self._starts: dict[tuple[str, str], list[float]] = defaultdict(list)

    async def record(self, event: str, *, attributes=None) -> None:
        attributes = attributes or {}
        server_id = str(attributes.get("server_id", "unknown"))
        operation = str(attributes.get("operation", "unknown"))
        key = (server_id, operation)

        if event == "operation.start":
            self._starts[key].append(time.monotonic())
            return
        if event in ("retry.success", "retry.failure"):
            _RETRIES_TOTAL.labels(outcome=event.rsplit(".", 1)[-1]).inc()
            return
        if event not in ("operation.success", "operation.failure"):
            return

        outcome = "success" if event == "operation.success" else "failure"
        _OPERATIONS_TOTAL.labels(server_id=server_id, operation=operation, outcome=outcome).inc()

        starts = self._starts[key]
        if starts:
            _OPERATION_DURATION.labels(server_id=server_id, operation=operation).observe(
                time.monotonic() - starts.pop(0)
            )

        if self.runtime is not None:
            health = await self.runtime.health(server_id)
            _SERVER_HEALTH.labels(server_id=server_id).set(_HEALTH_SCORE[health])

    async def record_discovery(self, server_id: str, result: RefreshResult) -> None:
        """Publish capability-discovery + refresh-outcome metrics for one server."""
        assert self.runtime is not None
        for capability_type in CapabilityType:
            count = len(await self.runtime.registry.list(server_id=server_id, type=capability_type))
            _CAPABILITIES_DISCOVERED.labels(server_id=server_id, type=capability_type.value).set(
                count
            )
        for field, value in (
            ("discovered", result.discovered_count),
            ("added", result.added_count),
            ("modified", result.modified_count),
            ("deleted", result.deleted_count),
        ):
            _REFRESH_LAST_RESULT.labels(server_id=server_id, field=field).set(value)


async def refresh_and_record(
    runtime: MCPRuntime, hook: ObservabilityMetricsHook, server_id: str
) -> RefreshResult:
    """Refresh one server and publish its discovery/refresh-outcome metrics."""
    result = await runtime.refresh_server(server_id)
    await hook.record_discovery(server_id, result)
    return result


class AlwaysFailingAdapter:
    """A permanently-broken server, scripted (not LLM-driven) to guarantee failure counters."""

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


async def generate_scripted_failure_traffic(runtime: MCPRuntime) -> None:
    broken_capability = (await runtime.retrieve("broken_call"))[0]
    for _ in range(5):
        try:
            await runtime.execute(broken_capability.capability_id)
        except Exception:
            pass


async def generate_real_llm_traffic(
    runtime: MCPRuntime, hook: ObservabilityMetricsHook, root: Path
) -> None:
    load_dotenv()
    api_key = os.environ.get("EXPLABS_API_KEY")
    if not api_key:
        raise SystemExit("Set EXPLABS_API_KEY in .env before running this example.")
    model = ChatOpenAI(
        model=os.environ.get("EXPLABS_MODEL", "gpt-5.6-luna"),
        base_url=os.environ.get("EXPLABS_BASE_URL", "https://api.experientiallabs.ai/v1"),
        api_key=api_key,
    )

    client = MultiServerMCPClient(
        {
            "filesystem": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-filesystem", str(root)],
                "transport": "stdio",
            }
        }
    )
    await runtime.register_mcp_client("filesystem", client, client_server_name="filesystem")
    await refresh_and_record(runtime, hook, "filesystem")

    selected = await runtime.retrieve("read a file", server_id="filesystem", limit=1)
    capability_id = selected[0].capability_id

    async def selected_tool(**arguments):
        return await runtime.execute(capability_id, arguments)

    tool = StructuredTool.from_function(
        coroutine=selected_tool,
        name=selected[0].name,
        description=selected[0].description or "Selected MCP capability",
        args_schema=selected[0].schema,
    )
    agent = create_agent(model=model, tools=[tool])
    for prompt in [
        "Read router-note.txt and tell me what it says.",
        "Read router-note.txt again and count its words.",
        "Read router-note.txt one more time and summarize it in one sentence.",
    ]:
        result = await agent.ainvoke({"messages": [{"role": "user", "content": prompt}]})
        print("LLM agent reply:", result["messages"][-1].content)


async def main() -> None:
    start_http_server(METRICS_PORT)
    print(f"Prometheus metrics exposed at http://0.0.0.0:{METRICS_PORT}/metrics")

    hook = ObservabilityMetricsHook()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "router-note.txt").write_text(
            "real MCP agent, real LLM, real Prometheus metrics", encoding="utf-8"
        )

        async with MCPRuntime(metrics=hook) as runtime:
            hook.runtime = runtime

            await runtime.register_server("broken", lambda: AlwaysFailingAdapter())
            await refresh_and_record(runtime, hook, "broken")

            await generate_real_llm_traffic(runtime, hook, root)
            await generate_scripted_failure_traffic(runtime)

            print("generated real LLM + scripted traffic; sample of exposed counters:")
            for metric in _OPERATIONS_TOTAL.collect():
                for sample in metric.samples:
                    print(" ", sample.name, sample.labels, sample.value)
            print("capability discovery and health:")
            for metric in (*_CAPABILITIES_DISCOVERED.collect(), *_SERVER_HEALTH.collect()):
                for sample in metric.samples:
                    print(" ", sample.name, sample.labels, sample.value)

            print(f"serving /metrics for {SERVE_SECONDS:.0f}s for an external scraper...")
            await asyncio.sleep(SERVE_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
