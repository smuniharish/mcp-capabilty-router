"""Metric names and fault-tolerant metric emission."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from refresh_engine import MetricsSink

logger = logging.getLogger("mcp_capability_router")

OPERATIONS = "mcp_capability_router.operations"
OPERATION_DURATION = "mcp_capability_router.operation.duration"
RETRIES = "mcp_capability_router.retries"
CIRCUIT_TRANSITIONS = "mcp_capability_router.circuit.transitions"


def increment(
    sink: MetricsSink | None, name: str, value: int, attributes: Mapping[str, str]
) -> None:
    """Add `value` to a counter; a failing sink never breaks an operation."""
    if sink is None:
        return
    try:
        sink.increment(name, value, attributes)
    except Exception:
        logger.exception("Metrics sink failed to record %s", name)


def observe(
    sink: MetricsSink | None, name: str, value: float, attributes: Mapping[str, str]
) -> None:
    """Record an observation; a failing sink never breaks an operation."""
    if sink is None:
        return
    try:
        sink.observe(name, value, attributes)
    except Exception:
        logger.exception("Metrics sink failed to record %s", name)


class ServerScopedSink:
    """Adds the `server_id` attribute to the refresh metrics of one server."""

    def __init__(self, sink: MetricsSink, server_id: str) -> None:
        """Wrap `sink` for the server `server_id`."""
        self._sink = sink
        self._server_id = server_id

    def increment(
        self,
        name: str,
        value: int = 1,
        attributes: Mapping[str, str] | None = None,
        /,
    ) -> None:
        """Add `value` to the counter `name`."""
        increment(self._sink, name, value, self._scoped(attributes))

    def observe(
        self,
        name: str,
        value: float,
        attributes: Mapping[str, str] | None = None,
        /,
    ) -> None:
        """Record one observation of `value` for the metric `name`."""
        observe(self._sink, name, value, self._scoped(attributes))

    def _scoped(self, attributes: Mapping[str, str] | None) -> dict[str, str]:
        return {**(attributes or {}), "server_id": self._server_id}
