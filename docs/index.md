---
hide:
  - navigation
---

# mcp-capability-router

**Give every agent the right MCP tools, resources, and prompts, from any number of
servers, through one resilient runtime.**

mcp-capability-router is an asyncio-first Python library that sits between your
agents and your MCP servers, whatever framework the agents use. It discovers what
each server offers, keeps that catalog current, ranks it against each request, and
runs every server operation through concurrency limits, circuit breakers, retries,
rate limits, and timeouts. An agent sees only the few tools that matter for the current turn,
however many servers and tools you register.

![Architecture](assets/diagrams/architecture-light.png#only-light)
![Architecture](assets/diagrams/architecture-dark.png#only-dark)

<div class="grid cards" markdown>

-   :material-target:{ .lg .middle } **Only the relevant tools**

    ---

    BM25, dense, or hybrid retrieval with RetrievalLoom, optionally reranked, selects
    the capabilities that
    match each request, so models stay fast, inexpensive, and accurate with thousands of
    tools.

-   :material-sync:{ .lg .middle } **Always current**

    ---

    Discovery runs on registration, on a schedule, on change notifications, or
    when a query finds nothing, and only what changed is written.

-   :material-shield-check-outline:{ .lg .middle } **Resilient by default**

    ---

    Every server operation runs through a concurrency limit, interceptors, a
    circuit breaker, retries, a rate limit, and a timeout.

-   :material-robot-outline:{ .lg .middle } **Any agent framework**

    ---

    Ready-to-call tools for any framework, LangChain middleware for `create_agent`
    and Deep Agents, and an MCP gateway that serves the router to any MCP client.

</div>

## Install

```bash
pip install mcp-capability-router
```

mcp-capability-router supports Python 3.12 through 3.14.

## A first route

Register a server, let the runtime discover its capabilities, and route a request
to the right tool:

<!-- test -->
```python
import asyncio

from fastmcp import FastMCP

from mcp_capability_router import MCPRuntime, RefreshPolicy

weather = FastMCP("weather")


@weather.tool
def get_forecast(city: str) -> str:
    """Get the weather forecast for a city."""
    return f"Sunny and 24 degrees in {city}"


@weather.tool
def list_alerts(region: str) -> list[str]:
    """List the active severe-weather alerts of a region."""
    return []


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_mcp("weather", weather, refresh=RefreshPolicy(on_register=True))
        [tool] = await runtime.route_tools("What is the forecast for Paris?", limit=1)
        print(tool.capability_id)

        result = await tool({"city": "Paris"})
        print(result.data)


asyncio.run(main())
```

Running the program prints:

```text
weather:tool:get_forecast
Sunny and 24 degrees in Paris
```

The server here runs in process; a URL, a script path, or an MCP configuration
works the same way. Retrieval ranks the discovered metadata without calling the
server, and the call runs through the resilience pipeline.

## Route tools for an agent

Each routed tool has a `name`, a `description`, and an `input_schema`, which any
[agent framework](guides/integrations.md) can show a model; awaiting it runs the MCP
tool through the runtime. With the `langchain` extra, add the middleware to a
LangChain agent, and every model call receives the tools that match the latest user
message:

```python
from langchain.agents import create_agent

from mcp_capability_router.integrations.langchain import CapabilityRoutingMiddleware

agent = create_agent(
    "openai:gpt-5.4-mini",
    tools=[],
    middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
)
result = await agent.ainvoke(
    {"messages": [{"role": "user", "content": "What is the forecast for Paris?"}]}
)
```

Any MCP client can reach the router through its [MCP gateway](guides/gateway.md).

## Downloads

<p>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=downloads&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Total downloads"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520date%2520%253E%253D%2520toStartOfWeek%2528today%2528%2529%252C%25201%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=this%20week&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads this week"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520date%2520%253E%253D%2520toStartOfMonth%2528today%2528%2529%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=this%20month&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads this month"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520sum%2528count%2529%2520v%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520date%2520%253E%253D%2520toStartOfYear%2528today%2528%2529%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=this%20year&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads this year"></a>
</p>
<p>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528groupArray%2528concat%2528toString%2528y%2529%252C%2520%2527%253A%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520toYear%2528date%2529%2520y%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520GROUP%2520BY%2520y%2520ORDER%2520BY%2520y%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=by%20year&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by year"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%2520LIMIT%25205%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=top%20countries&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Top 5 download countries"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527A%2527%2520AND%2520%2527A%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20A&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country A"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527B%2527%2520AND%2520%2527B%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20B&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country B"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527C%2527%2520AND%2520%2527C%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20C&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country C"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527D%2527%2520AND%2520%2527D%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20D&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country D"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527E%2527%2520AND%2520%2527E%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20E&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country E"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527F%2527%2520AND%2520%2527F%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20F&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country F"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527G%2527%2520AND%2520%2527G%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20G&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country G"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527H%2527%2520AND%2520%2527H%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20H&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country H"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527I%2527%2520AND%2520%2527I%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20I&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country I"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527J%2527%2520AND%2520%2527J%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20J&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country J"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527K%2527%2520AND%2520%2527K%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20K&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country K"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527L%2527%2520AND%2520%2527L%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20L&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country L"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527M%2527%2520AND%2520%2527M%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20M&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country M"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527N%2527%2520AND%2520%2527O%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20N-O&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country N-O"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527P%2527%2520AND%2520%2527Q%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20P-Q&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country P-Q"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527R%2527%2520AND%2520%2527R%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20R&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country R"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527S%2527%2520AND%2520%2527S%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20S&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country S"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527T%2527%2520AND%2520%2527T%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20T&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country T"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528country_code%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520substring%2528country_code%252C%25201%252C%25201%2529%2520BETWEEN%2520%2527U%2527%2520AND%2520%2527Y%2527%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20U-Y&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country U-Y"></a>
  <a href="https://clickpy.clickhouse.com/dashboard/mcp-capability-router"><img src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fsql-clickhouse.clickhouse.com%2F%3Fuser%3Ddemo%26query%3DSELECT%2520if%2528empty%2528arrayStringConcat%2528groupArray%2528concat%2528if%2528empty%2528country_code%2529%252C%2520%2527unknown%2527%252C%2520country_code%2529%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%252C%2520%2527none%2527%252C%2520arrayStringConcat%2528groupArray%2528concat%2528if%2528empty%2528country_code%2529%252C%2520%2527unknown%2527%252C%2520country_code%2529%252C%2520%2527%2520%2527%252C%2520toString%2528c%2529%2529%2529%252C%2520%2527%2520%257C%2520%2527%2529%2529%2520v%2520FROM%2520%2528SELECT%2520ifNull%2528country_code%252C%2520%2527%2527%2529%2520AS%2520country_code%252C%2520sum%2528count%2529%2520c%2520FROM%2520pypi.pypi_downloads_per_day_by_version_by_country%2520WHERE%2520project%253D%2527mcp-capability-router%2527%2520AND%2520%2528startsWith%2528country_code%252C%2520%2527Z%2527%2529%2520OR%2520NOT%2520match%2528ifNull%2528country_code%252C%2520%2527%2527%2529%252C%2520%2527%255E%255BA-Z%255D%2527%2529%2529%2520GROUP%2520BY%2520country_code%2520ORDER%2520BY%2520c%2520DESC%252C%2520country_code%2529%2520FORMAT%2520JSON&amp;query=%24.data%5B0%5D.v&amp;label=countries%20Z%20and%20other&amp;color=blue&amp;cacheSeconds=3600" class="off-glb" alt="Downloads by country Z and other"></a>
</p>

Counts come from the [ClickHouse public PyPI dataset](https://clickpy.clickhouse.com/dashboard/mcp-capability-router),
which refreshes daily, so they may be about a day behind. Shields fetches the data
when a badge is requested and caches the image for up to an hour; GitHub may also
cache images. Weeks start on Monday (UTC). Explore interactive
[download charts](https://clickpy.clickhouse.com/dashboard/mcp-capability-router) on ClickPy.

## Where to go next

- [Getting started](getting-started.md) builds a complete integration step by step.
- [Concepts](concepts.md) explains capabilities, discovery, retrieval, and the
  resilience pipeline.
- The [guides](guides/index.md) cover each capability in depth.
- The [examples](examples.md) show every feature in a runnable program.
- The [API reference](api/index.md) documents every public name.
