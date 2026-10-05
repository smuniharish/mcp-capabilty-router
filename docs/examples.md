# Examples

These programs use only the public API. Find them, with instructions for running
them, in the
[`examples`](https://github.com/smuniharish/mcp-capabilty-router/tree/HEAD/examples)
directory of the repository. The demo servers run in process, so most examples need
no network, no subprocess, and no credentials, and their output is verified in
continuous integration. Most of them share this module:

??? example "`common.py`: demo MCP servers and helpers"

    ```python
    --8<--
    examples/common.py
    --8<--
    ```

## Quick start

=== "Program"

    ```python
    --8<--
    examples/01_quickstart.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/01_quickstart.txt
    --8<--
    ```

## Tools, resources, and prompts

=== "Program"

    ```python
    --8<--
    examples/02_capability_types.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/02_capability_types.txt
    --8<--
    ```

## Lazy registration and isolated tenants

=== "Program"

    ```python
    --8<--
    examples/03_lazy_and_isolated.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/03_lazy_and_isolated.txt
    --8<--
    ```

## Refresh policies

=== "Program"

    ```python
    --8<--
    examples/04_refresh_policies.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/04_refresh_policies.txt
    --8<--
    ```

## Resilience

=== "Program"

    ```python
    --8<--
    examples/05_resilience.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/05_resilience.txt
    --8<--
    ```

## Observability

=== "Program"

    ```python
    --8<--
    examples/06_observability.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/06_observability.txt
    --8<--
    ```

## A durable registry on SQLite

=== "Program"

    ```python
    --8<--
    examples/07_custom_registry.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/07_custom_registry.txt
    --8<--
    ```

## Semantic retrieval

Requires an embedding model: set `MCP_ROUTER_EXAMPLE_EMBEDDINGS`, such as
`openai:text-embedding-3-small`, and the provider's credentials.

```python
--8<--
examples/08_semantic_retrieval.py
--8<--
```

## A LangGraph workflow

=== "Program"

    ```python
    --8<--
    examples/09_langgraph_workflow.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/09_langgraph_workflow.txt
    --8<--
    ```

## Agent middleware

Requires a chat model: set `MCP_ROUTER_EXAMPLE_MODEL`, such as
`openai:gpt-5.4-mini`, and the provider's credentials.

```python
--8<--
examples/10_agent_middleware.py
--8<--
```

## Deep Agents

Requires a chat model, as above.

```python
--8<--
examples/11_deep_agent.py
--8<--
```

## An agent swarm

Requires a chat model, as above.

```python
--8<--
examples/12_agent_swarm.py
--8<--
```

## A registry shared through PostgreSQL

Requires a PostgreSQL database: set `MCP_ROUTER_EXAMPLE_POSTGRES_DSN`.

=== "Program"

    ```python
    --8<--
    examples/13_postgres_registry.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/13_postgres_registry.txt
    --8<--
    ```

## Official MCP servers over stdio

Requires Node.js with `npx`: set `MCP_ROUTER_EXAMPLE_NODE=1`.

```python
--8<--
examples/14_stdio_servers.py
--8<--
```

## Scale

=== "Program"

    ```python
    --8<--
    examples/15_scale.py
    --8<--
    ```

=== "Output"

    ```text
    --8<--
    examples/output/15_scale.txt
    --8<--
    ```
