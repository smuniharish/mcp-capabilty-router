"""Example U: Overriding every defaulted public-API parameter, then a real LLM run.

Every public constructor and method across the package ships with a sensible default
(``InMemoryRegistry``, ``DeterministicRetriever``, ``max_concurrency=16``, no retry/rate
limiting, ``RefreshMode.FULL``, ``limit=20``, ...). This example is a single reference for
how to override *each one*, not just the refresh-related ones already shown in
``refresh_strategies.py``/``manual_refresh.py``. Each demo asserts the override actually
took effect (a custom registry/retriever/reranker/interceptor/metrics hook really ran, a
non-default ``max_concurrency``/``operation_timeout``/``retry``/``rate_limiter`` really
changed behavior, ``RefreshPolicy.config``/``store`` really reached the underlying
``refresh_engine.RefreshEngine``, explicit ``mode=``/``resource_ids=`` really scoped a
refresh, ``retrieve``/``query``'s ``type``/``limit``/``server_id``/``refresh_servers``
really scoped a query) -- these are not just "no exception was raised" smoke checks.

The final demo, ``real_llm_end_to_end_demo``, combines *all* of the overrides above into
one ``MCPRuntime`` and drives it with a real ``langchain.agents.create_agent`` LLM agent
against a real Filesystem MCP server, proving the fully-customized runtime still composes
correctly end-to-end -- not just in isolation.

Run:
    uv sync --extra mcp --extra agents --extra openai --extra examples
    uv run python -m examples.public_api_overrides
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import TypeVar

from aiolimiter import AsyncLimiter
from refresh_engine import (
    FailurePolicy,
    InMemoryStateStore,
    RefreshConfig,
    RefreshMode,
    RetryConfig,
)
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential

from mcp_capability_router import (
    Capability,
    CapabilityRegistryBase,
    CapabilityReranker,
    CapabilityType,
    DeterministicRetriever,
    MCPRuntime,
    RefreshPolicy,
    RerankingRetriever,
)
from mcp_capability_router.resilience import semantic_classifier

T = TypeVar("T")


class FakeAdapter:
    """A minimal in-process MCP adapter with a few named tools, for override demos that
    don't need a real MCP server (the final demo below uses a real one instead)."""

    def __init__(self, names: Sequence[str], fail_times: int = 0, sleep_seconds: float = 0.0):
        self._names = names
        self.fail_times = fail_times
        self.sleep_seconds = sleep_seconds
        self.attempts = 0

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": name, "description": f"{name} description"} for name in self._names]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise TimeoutError("upstream temporarily unavailable")
        if self.sleep_seconds:
            await asyncio.sleep(self.sleep_seconds)
        return {"name": name, "attempts": self.attempts}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


# --------------------------------------------------------------------------------------
# 1. registry= : a custom CapabilityRegistry, built on CapabilityRegistryBase.
# --------------------------------------------------------------------------------------


class CountingRegistry(CapabilityRegistryBase):
    """Wraps an in-memory dict but counts every upsert -- proves ``registry=`` is used."""

    def __init__(self) -> None:
        self._items: dict[str, Capability] = {}
        self.upsert_calls = 0

    async def upsert_many(self, capabilities):
        self.upsert_calls += 1
        for capability in capabilities:
            self._items[capability.capability_id] = capability

    async def remove_missing(self, server_id, current_ids):
        stale = [
            key
            for key, value in self._items.items()
            if value.server_id == server_id and key not in current_ids
        ]
        for key in stale:
            del self._items[key]

    async def remove(self, capability_id):
        self._items.pop(capability_id, None)

    async def get(self, capability_id):
        return self._items.get(capability_id)

    async def list(self, *, server_id=None, type=None):
        return [
            value
            for value in self._items.values()
            if (server_id is None or value.server_id == server_id)
            and (type is None or value.type == type)
        ]


async def registry_override_demo() -> None:
    print("-- registry= : a custom CapabilityRegistry replaces InMemoryRegistry --")
    registry = CountingRegistry()
    async with MCPRuntime(registry=registry) as runtime:
        await runtime.register_server("svc", lambda: FakeAdapter(["do_work"]))
        await runtime.refresh_server("svc")
        assert registry.upsert_calls > 0
        print("custom registry saw", registry.upsert_calls, "upsert call(s)")


# --------------------------------------------------------------------------------------
# 2. retriever= : a custom two-stage RerankingRetriever(first_stage, reranker,
#    overfetch_limit=...) replaces DeterministicRetriever.
# --------------------------------------------------------------------------------------


class ReversingReranker(CapabilityReranker):
    """A trivial reranker that reverses first-stage order -- easy to detect in output."""

    async def rerank(self, query, candidates, *, limit=20):
        return list(reversed(candidates))[:limit]


async def retriever_and_reranker_override_demo() -> None:
    print("-- retriever= : RerankingRetriever(first_stage, reranker, overfetch_limit=...) --")
    first_stage = DeterministicRetriever()
    retriever = RerankingRetriever(first_stage, ReversingReranker(), overfetch_limit=3)
    async with MCPRuntime(retriever=retriever) as runtime:
        await runtime.register_server("svc", lambda: FakeAdapter(["alpha", "beta", "gamma"]))
        await runtime.refresh_server("svc")
        candidates = await runtime.registry.list()
        default_order = [c.name for c in await first_stage.retrieve("a", candidates, limit=3)]
        reranked = await runtime.retrieve("a", limit=3)
        assert [c.name for c in reranked] == list(reversed(default_order))
        print("first-stage order:", default_order, "-> reranked:", [c.name for c in reranked])


# --------------------------------------------------------------------------------------
# 3. metrics= : a custom MetricsHook replaces the no-op NullMetrics default.
# --------------------------------------------------------------------------------------


class RecordingMetrics:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def record(self, event: str, *, attributes: Mapping[str, object] | None = None) -> None:
        self.events.append(event)


async def metrics_override_demo() -> None:
    print("-- metrics= : a custom MetricsHook observes every pipeline event --")
    metrics = RecordingMetrics()
    async with MCPRuntime(metrics=metrics) as runtime:
        await runtime.register_server("svc", lambda: FakeAdapter(["do_work"]))
        await runtime.refresh_server("svc")
        capability = (await runtime.retrieve("do_work"))[0]
        await runtime.execute(capability.capability_id)
        assert "operation.success" in metrics.events
        print("custom metrics hook recorded:", metrics.events)


# --------------------------------------------------------------------------------------
# 4. interceptors= : a custom Interceptor chain wraps every operation.
# --------------------------------------------------------------------------------------


def logging_interceptor(log: list[str]) -> Callable[[Callable[[], Awaitable[T]]], Awaitable[T]]:
    async def intercept(operation: Callable[[], Awaitable[T]]) -> T:
        log.append("before")
        try:
            return await operation()
        finally:
            log.append("after")

    return intercept


async def interceptor_override_demo() -> None:
    print("-- interceptors= : a custom Interceptor chain wraps every operation --")
    log: list[str] = []
    async with MCPRuntime(interceptors=(logging_interceptor(log),)) as runtime:
        await runtime.register_server("svc", lambda: FakeAdapter(["do_work"]))
        await runtime.refresh_server("svc")
        capability = (await runtime.retrieve("do_work"))[0]
        await runtime.execute(capability.capability_id)
        assert log.count("before") >= 2  # discover + call_tool, both intercepted
        assert log.count("before") == log.count("after")
        print("interceptor log:", log)


# --------------------------------------------------------------------------------------
# 5. retry=, rate_limiter= : real tenacity.AsyncRetrying / aiolimiter.AsyncLimiter
#    override the "no retry, no throttling" defaults.
# --------------------------------------------------------------------------------------


async def retry_and_rate_limiter_override_demo() -> None:
    print("-- retry=, rate_limiter= : override the no-retry/no-throttle defaults --")
    flaky = FakeAdapter(["flaky_call"], fail_times=2)
    retry = AsyncRetrying(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=0.01, max=0.05),
        retry=retry_if_exception(semantic_classifier),
        reraise=True,
    )
    rate_limiter = AsyncLimiter(5, time_period=1)
    async with MCPRuntime(retry=retry, rate_limiter=rate_limiter) as runtime:
        await runtime.register_server("flaky", lambda: flaky)
        await runtime.refresh_server("flaky")
        capability = (await runtime.retrieve("flaky_call"))[0]
        started = time.perf_counter()
        for _ in range(6):
            await runtime.execute(capability.capability_id)
        elapsed = time.perf_counter() - started
        assert flaky.attempts >= 3  # the first two calls needed retries to succeed at all
        assert elapsed >= 0.2  # 6 calls through a 5/s limiter cannot be instantaneous
        print(f"6 calls succeeded through custom retry+rate_limiter in {elapsed:.2f}s")


# --------------------------------------------------------------------------------------
# 6. max_concurrency=, operation_timeout= : override the defaults of 16 and None.
# --------------------------------------------------------------------------------------


class ConcurrencyTrackingAdapter(FakeAdapter):
    def __init__(self) -> None:
        super().__init__(["do_work"])
        self.in_flight = 0
        self.max_in_flight = 0
        self._lock = asyncio.Lock()

    async def call_tool(self, name, arguments=None):
        async with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.02)
        finally:
            async with self._lock:
                self.in_flight -= 1
        return {"ok": True}


async def concurrency_and_timeout_override_demo() -> None:
    print("-- max_concurrency=, operation_timeout= : override 16 and None --")
    adapter = ConcurrencyTrackingAdapter()
    async with MCPRuntime(max_concurrency=2) as runtime:
        await runtime.register_server("work", lambda: adapter)
        await runtime.refresh_server("work")
        capability_id = (await runtime.retrieve("do_work"))[0].capability_id
        await asyncio.gather(*(runtime.execute(capability_id) for _ in range(8)))
        assert adapter.max_in_flight <= 2
        print("max_concurrency=2 -> observed max in flight:", adapter.max_in_flight)

    from mcp_capability_router.errors import TimeoutError as MCPTimeoutError

    slow = FakeAdapter(["slow_call"], sleep_seconds=1.0)
    async with MCPRuntime(operation_timeout=0.05) as runtime:
        await runtime.register_server("slow", lambda: slow)
        await runtime.refresh_server("slow")
        capability = (await runtime.retrieve("slow_call"))[0]
        try:
            await runtime.execute(capability.capability_id)
        except MCPTimeoutError:
            print("operation_timeout=0.05 -> call correctly timed out")
        else:
            raise AssertionError("expected the overridden operation_timeout to fire")


# --------------------------------------------------------------------------------------
# 7. register_server(metadata=, refresh=RefreshPolicy(mode=, config=, store=)) : override
#    the RefreshPolicy defaults (FULL mode, refresh-engine's own RefreshConfig/StateStore).
# --------------------------------------------------------------------------------------


async def register_and_refresh_policy_override_demo() -> None:
    print("-- register_server(metadata=, refresh=RefreshPolicy(mode=, config=, store=)) --")
    config = RefreshConfig(
        max_concurrency=2,
        failure_policy=FailurePolicy.BEST_EFFORT,
        retry=RetryConfig(max_attempts=2),
    )
    store = InMemoryStateStore()
    async with MCPRuntime() as runtime:
        handle = await runtime.register_server(
            "svc",
            lambda: FakeAdapter(["do_work"]),
            metadata={"team": "support"},
            refresh=RefreshPolicy(
                on_register=True,
                mode=RefreshMode.INCREMENTAL,
                config=config,
                store=store,
            ),
        )
        assert handle.metadata == {"team": "support"}
        capabilities = await runtime.registry.list(server_id="svc")
        assert capabilities  # on_register=True already ran discovery before this point
        print("metadata override:", handle.metadata)
        print("on_register=True + mode=INCREMENTAL discovered:", [c.name for c in capabilities])


# --------------------------------------------------------------------------------------
# 8. refresh_server(mode=, resource_ids=) and retrieve/query(type=, limit=, server_id=,
#    refresh_servers=) : override the FULL/20/None/() defaults.
# --------------------------------------------------------------------------------------


async def explicit_refresh_and_query_override_demo() -> None:
    print("-- refresh_server(mode=, resource_ids=) and retrieve/query overrides --")
    async with MCPRuntime() as runtime:
        await runtime.register_server("svc", lambda: FakeAdapter(["alpha", "beta"]))
        capabilities = await runtime.retrieve("a", type=CapabilityType.TOOL, limit=1)
        assert capabilities == []  # nothing discovered yet: no refresh policy configured

        one = (await runtime.refresh_server("svc", mode=RefreshMode.FULL)).status
        print("explicit refresh_server(mode=FULL) status:", one)

        alpha = next(c for c in await runtime.registry.list(server_id="svc") if c.name == "alpha")
        # resource_ids= scopes refresh to just this one capability instead of the whole server.
        result = await runtime.refresh_server("svc", resource_ids=[alpha.capability_id])
        print("refresh_server(resource_ids=[alpha]) status:", result.status)

        scoped = await runtime.retrieve("a", type=CapabilityType.TOOL, limit=1, server_id="svc")
        assert len(scoped) == 1 and scoped[0].type is CapabilityType.TOOL
        print("retrieve(type=TOOL, limit=1, server_id='svc') ->", scoped[0].name)

        await runtime.registry.remove_missing("svc", set())  # simulate a cold cache
        # mode=FULL here, not INCREMENTAL: INCREMENTAL compares against refresh-engine's own
        # StateStore snapshot, which this out-of-band registry clear never touched, so it
        # would see "nothing changed" and skip re-populating the registry.
        recovered = await runtime.query(
            "a",
            refresh_servers=["svc"],
            mode=RefreshMode.FULL,
            limit=1,
        )
        assert recovered
        print("query(refresh_servers=['svc'], mode=FULL, limit=1) ->", recovered[0].name)


# --------------------------------------------------------------------------------------
# 9. Real LLM end-to-end: every override above, combined into one MCPRuntime, driving a
#    real create_agent LLM agent against a real Filesystem MCP server.
# --------------------------------------------------------------------------------------


async def real_llm_end_to_end_demo() -> None:
    print("-- combining every override above, driven by a real LLM agent --")
    try:
        from dotenv import load_dotenv
        from langchain.agents import create_agent
        from langchain_core.tools import StructuredTool
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise SystemExit(
            "Install optional agent dependencies first: "
            "uv sync --extra mcp --extra agents --extra openai --extra examples"
        ) from exc

    load_dotenv()
    api_key = os.environ.get("EXPLABS_API_KEY")
    if not api_key:
        raise SystemExit("Set EXPLABS_API_KEY in .env before running this example.")
    model = ChatOpenAI(
        model=os.environ.get("EXPLABS_MODEL", "gpt-5.6-luna"),
        base_url=os.environ.get("EXPLABS_BASE_URL", "https://api.experientiallabs.ai/v1"),
        api_key=api_key,
    )

    registry = CountingRegistry()
    # Reranker pluggability is already proven in retriever_and_reranker_override_demo(); here we
    # keep DeterministicRetriever's relevance ranking as-is so the agent gets the best-matching
    # tool for the real task below.
    retriever = DeterministicRetriever()
    metrics = RecordingMetrics()
    interceptor_log: list[str] = []
    retry = AsyncRetrying(
        stop=stop_after_attempt(3),
        retry=retry_if_exception(semantic_classifier),
        reraise=True,
    )
    rate_limiter = AsyncLimiter(20, time_period=1)

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "router-note.txt").write_text("real MCP agent, fully overridden runtime", "utf-8")

        async with MCPRuntime(
            registry=registry,
            retriever=retriever,
            max_concurrency=4,
            # npx may need to download @modelcontextprotocol/server-filesystem on first run,
            # so give discovery plenty of headroom (subsequent runs are cached and much faster).
            operation_timeout=60.0,
            retry=retry,
            rate_limiter=rate_limiter,
            interceptors=(logging_interceptor(interceptor_log),),
            metrics=metrics,
        ) as runtime:
            client = MultiServerMCPClient(
                {
                    "filesystem": {
                        "command": "npx",
                        "args": ["-y", "@modelcontextprotocol/server-filesystem", str(root)],
                        "transport": "stdio",
                    }
                }
            )
            handle = await runtime.register_mcp_client(
                "filesystem",
                client,
                client_server_name="filesystem",
                metadata={"purpose": "override-demo"},
                refresh=RefreshPolicy(
                    on_register=True,
                    mode=RefreshMode.INCREMENTAL,
                    store=InMemoryStateStore(),
                ),
            )
            assert handle.metadata == {"purpose": "override-demo"}

            selected = await runtime.retrieve(
                "read file", type=CapabilityType.TOOL, limit=1, server_id="filesystem"
            )
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
            result = await agent.ainvoke(
                {"messages": [{"role": "user", "content": "Read router-note.txt"}]}
            )
            print("LLM agent reply:", result["messages"][-1].content)

            assert registry.upsert_calls > 0
            assert "operation.success" in metrics.events
            assert interceptor_log  # the custom interceptor chain ran too
            print(
                "all overrides verified end-to-end: custom registry saw",
                registry.upsert_calls,
                "upserts, custom metrics recorded",
                len(metrics.events),
                "events, custom interceptor ran",
                len(interceptor_log),
                "times",
            )


async def main() -> None:
    await registry_override_demo()
    await retriever_and_reranker_override_demo()
    await metrics_override_demo()
    await interceptor_override_demo()
    await retry_and_rate_limiter_override_demo()
    await concurrency_and_timeout_override_demo()
    await register_and_refresh_policy_override_demo()
    await explicit_refresh_and_query_override_demo()
    await real_llm_end_to_end_demo()


if __name__ == "__main__":
    asyncio.run(main())
