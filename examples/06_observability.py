"""Export router and refresh metrics, in memory or to Prometheus.

The runtime reports counters and durations to any refresh-engine metrics sink:
the pipeline metrics of every server operation, and the refresh metrics of every
server. A sink is any object with `increment` and `observe` methods.
"""

import asyncio
import contextlib
from collections.abc import Mapping

from common import billing_server, crm_server
from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest
from refresh_engine import InMemoryMetrics

from mcp_capability_router import MCPRuntime, RefreshPolicy, ToolExecutionError


class PrometheusSink:
    """Bridges refresh-engine metrics to prometheus_client."""

    def __init__(self, registry: CollectorRegistry) -> None:
        self._registry = registry
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    @staticmethod
    def _name(name: str) -> str:
        return name.replace(".", "_")

    def increment(
        self, name: str, value: int = 1, attributes: Mapping[str, str] | None = None, /
    ) -> None:
        labels = dict(sorted((attributes or {}).items()))
        counter = self._counters.get(name)
        if counter is None:
            counter = Counter(
                self._name(name), name, list(labels), registry=self._registry
            )
            self._counters[name] = counter
        counter.labels(**labels).inc(value)

    def observe(
        self, name: str, value: float, attributes: Mapping[str, str] | None = None, /
    ) -> None:
        labels = dict(sorted((attributes or {}).items()))
        histogram = self._histograms.get(name)
        if histogram is None:
            histogram = Histogram(
                self._name(name), name, list(labels), registry=self._registry
            )
            self._histograms[name] = histogram
        histogram.labels(**labels).observe(value)


class Fanout:
    """Sends every metric to several sinks."""

    def __init__(self, *sinks: InMemoryMetrics | PrometheusSink) -> None:
        self._sinks = sinks

    def increment(
        self, name: str, value: int = 1, attributes: Mapping[str, str] | None = None, /
    ) -> None:
        for sink in self._sinks:
            sink.increment(name, value, attributes)

    def observe(
        self, name: str, value: float, attributes: Mapping[str, str] | None = None, /
    ) -> None:
        for sink in self._sinks:
            sink.observe(name, value, attributes)


async def main() -> None:
    memory = InMemoryMetrics()
    prometheus = CollectorRegistry()
    async with MCPRuntime(
        metrics=Fanout(memory, PrometheusSink(prometheus))
    ) as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.execute("crm:tool:search_customers", {"query": "acme"})
        await runtime.read_resource("billing:resource:billing://policies/refunds")
        with contextlib.suppress(ToolExecutionError):
            await runtime.execute(
                "billing:tool:issue_refund", {"invoice_id": "inv-2", "amount": 10}
            )

    counters, _ = memory.snapshot()
    print("in-memory counters:")
    for name in sorted(counters):
        if name.startswith(
            ("mcp_capability_router.operations", "refresh_engine.refreshes")
        ):
            print(f"  {name} = {counters[name]}")

    print("\nPrometheus exposition (counters):")
    for line in generate_latest(prometheus).decode().splitlines():
        if line.startswith("mcp_capability_router_operations_total"):
            print(f"  {line}")


if __name__ == "__main__":
    asyncio.run(main())
