"""Example P: Bulkhead concurrency limiting + rate limiting on one runtime.

Run:
    uv run python -m examples.resilience_bulkhead_rate_limit

Credential-free: demonstrates ``MCPRuntime(max_concurrency=...)`` (the bulkhead) capping
how many concurrent operations a server admits at once, and ``MCPRuntime(rate_limiter=...)``
throttling the sustained call rate by passing a real ``aiolimiter.AsyncLimiter`` directly --
both configured purely through constructor arguments, with no custom thread-pool or
scheduler code required.
"""

from __future__ import annotations

import asyncio
import time

from aiolimiter import AsyncLimiter

from mcp_capability_router import MCPRuntime


class ConcurrencyTrackingAdapter:
    """Reports the maximum number of ``call_tool`` invocations in flight at once."""

    def __init__(self, work_seconds: float) -> None:
        self.work_seconds = work_seconds
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = asyncio.Lock()

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "do_work", "description": "simulated concurrent work"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        async with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.work_seconds)
        finally:
            async with self._lock:
                self.in_flight -= 1
        return {"ok": True}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def bulkhead_demo() -> None:
    print("-- bulkhead caps concurrent in-flight calls --")
    adapter = ConcurrencyTrackingAdapter(work_seconds=0.05)
    async with MCPRuntime(max_concurrency=2) as runtime:
        await runtime.register_server("work", lambda: adapter)
        await runtime.refresh_server("work")
        capability_id = (await runtime.retrieve("do_work"))[0].capability_id
        await asyncio.gather(*(runtime.execute(capability_id) for _ in range(8)))
        print(
            "8 concurrent requests, max_concurrency=2 -> "
            f"observed max in flight: {adapter.max_in_flight}"
        )
        assert adapter.max_in_flight <= 2


async def rate_limit_demo() -> None:
    print("-- rate limiter throttles sustained call rate --")
    adapter = ConcurrencyTrackingAdapter(work_seconds=0.0)
    # 5 tokens per 1 second: 10 sequential calls should take at least ~1.8s (9 gaps @ 0.2s).
    # Built directly from aiolimiter's own constructor for full control over burst
    # capacity/time period.
    limiter = AsyncLimiter(5, time_period=1)
    async with MCPRuntime(rate_limiter=limiter) as runtime:
        await runtime.register_server("throttled", lambda: adapter)
        await runtime.refresh_server("throttled")
        capability_id = (await runtime.retrieve("do_work"))[0].capability_id
        started = time.perf_counter()
        for _ in range(10):
            await runtime.execute(capability_id)
        elapsed = time.perf_counter() - started
        print(f"10 calls at a custom AsyncLimiter(5, time_period=1) took {elapsed:.2f}s")
        assert elapsed >= 1.5


async def main() -> None:
    await bulkhead_demo()
    await rate_limit_demo()


if __name__ == "__main__":
    asyncio.run(main())
