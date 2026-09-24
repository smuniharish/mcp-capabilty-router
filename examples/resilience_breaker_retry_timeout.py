"""Example O: Circuit breaker + retry + timeout acting together on one runtime.

Run:
    uv run python -m examples.resilience_breaker_retry_timeout

Credential-free: a flaky adapter fails a configurable number of times before
succeeding, and a slow adapter sleeps past the configured operation timeout.
Demonstrates ``MCPRuntime(retry=..., operation_timeout=...)`` retrying transient
failures automatically, the circuit breaker opening once a server degrades
persistently, and building the ``tenacity.AsyncRetrying`` passed to ``retry=``
directly from ``tenacity``'s own primitives for full control over backoff/retry
predicates.
"""

from __future__ import annotations

import asyncio

from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from mcp_capability_router import MCPRuntime
from mcp_capability_router.errors import TimeoutError as MCPTimeoutError
from mcp_capability_router.resilience import semantic_classifier
from mcp_capability_router.server import HealthState


def _retrying(attempts: int) -> AsyncRetrying:
    """Build the ``tenacity.AsyncRetrying`` passed to ``MCPRuntime(retry=...)``."""
    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        retry=retry_if_exception(semantic_classifier),
        reraise=True,
    )


class FlakyAdapter:
    """Fails a fixed number of times, then succeeds -- a transient-failure case."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
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
        if self.attempts <= self.fail_times:
            raise TimeoutError("upstream temporarily unavailable")
        return {"attempts": self.attempts}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


class AlwaysFailingAdapter:
    """Fails every call -- the case that should trip the circuit breaker open."""

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


class SlowAdapter:
    """Sleeps past the runtime's ``operation_timeout`` -- the timeout demo case."""

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "slow_call", "description": "takes too long"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        await asyncio.sleep(1.0)
        return {"ok": True}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def retry_demo() -> None:
    print("-- retry recovers from a transient failure --")
    flaky = FlakyAdapter(fail_times=2)
    async with MCPRuntime(retry=_retrying(3)) as runtime:
        await runtime.register_server("flaky", lambda: flaky)
        await runtime.refresh_server("flaky")
        capability = (await runtime.retrieve("flaky_call"))[0]
        result = await runtime.execute(capability.capability_id)
        print("succeeded after retries:", result, "-> attempts made:", flaky.attempts)


async def circuit_breaker_demo() -> None:
    print("-- circuit breaker opens after repeated failures --")
    async with MCPRuntime() as runtime:
        await runtime.register_server("broken", lambda: AlwaysFailingAdapter())
        await runtime.refresh_server("broken")
        capability = (await runtime.retrieve("broken_call"))[0]
        for attempt in range(1, 6):
            try:
                await runtime.execute(capability.capability_id)
            except Exception as error:
                print(f"attempt {attempt} failed: {type(error).__name__}: {error}")
        print("server health after repeated failures:", await runtime.health("broken"))
        assert await runtime.health("broken") in (HealthState.DEGRADED, HealthState.UNHEALTHY)


async def timeout_demo() -> None:
    print("-- operation timeout bounds a slow call --")
    async with MCPRuntime(operation_timeout=0.1) as runtime:
        await runtime.register_server("slow", lambda: SlowAdapter())
        await runtime.refresh_server("slow")
        capability = (await runtime.retrieve("slow_call"))[0]
        try:
            await runtime.execute(capability.capability_id)
        except MCPTimeoutError as error:
            print("call correctly timed out:", error)


async def custom_tenacity_retry_demo() -> None:
    print("-- a real tenacity.AsyncRetrying configures backoff/retry predicates directly --")
    flaky = FlakyAdapter(fail_times=2)
    custom_retry = AsyncRetrying(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=0.01, max=0.1),
        retry=retry_if_exception_type(TimeoutError),
        reraise=True,
    )
    async with MCPRuntime(retry=custom_retry) as runtime:
        await runtime.register_server("flaky-custom", lambda: flaky)
        await runtime.refresh_server("flaky-custom")
        capability = (await runtime.retrieve("flaky_call"))[0]
        result = await runtime.execute(capability.capability_id)
        print("succeeded with custom backoff:", result, "-> attempts made:", flaky.attempts)


async def main() -> None:
    await retry_demo()
    await custom_tenacity_retry_demo()
    await circuit_breaker_demo()
    await timeout_demo()


if __name__ == "__main__":
    asyncio.run(main())
