# Performance

The router adds little to the cost of an MCP call: the network and the server
dominate. These measurements show the router's own overhead, with in-memory adapters
and no network.

## Benchmark results

Measured with CPython 3.12 on a laptop. Treat the numbers as indicative, and run the
benchmarks on your own hardware with `python benchmarks/bench_retrieval.py` and
`python benchmarks/bench_runtime.py` from the repository.

### Retrieval

Median latency of one query over a catalog of tools:

| Capabilities | `KeywordRetriever` | `EmbeddingRetriever` |
| ---: | ---: | ---: |
| 100 | 0.09 ms | 1.5 ms |
| 1,000 | 0.9 ms | 8.4 ms |
| 10,000 | 10 ms | 73 ms |
| 100,000 | 195 ms | — |

The embedding benchmark uses a hash function instead of a model, so it measures the
vector search; a real embedding model adds one embedding call per query.

### Refresh and execution

| Measurement | 1,000 tools | 10,000 tools |
| --- | ---: | ---: |
| First refresh | 32 ms | 422 ms |
| Refresh with nothing changed | 33 ms | 289 ms |
| `execute` through the full pipeline, median | 6 µs | 5 µs |

## Tuning advice

**Narrow the candidates.** Retrieval time grows linearly with the number of
candidates. Pass `type` and `server_id` when you know them, and scope agents to the
servers they need. Keyword indexes are cached per capability and rebuilt only when a
capability changes.

**Prefer change notifications to short intervals.** Every refresh lists the whole
server, even when nothing changed. Refresh on `list_changed` notifications or on query
misses, and keep intervals long as a safety net.

**Keep connections open.** The runtime holds one session per server for its whole
lifetime. Avoid calling `reconnect` or recreating runtimes per request; create runtimes
per tenant and reuse them.

**Size the concurrency limit.** `max_concurrency` bounds the operations in flight
across all servers. Raise it for many fast servers; lower it to protect slow ones, or
limit them separately with an interceptor.

**Set timeouts.** A server that stops answering holds a concurrency slot until the
operation times out. `operation_timeout` frees it.

**Embed once.** `EmbeddingRetriever` embeds each capability once and again only when
its text changes. Keep one retriever per runtime, and size `max_documents` to your
catalog, so that vectors are not evicted and embedded again.

**Cold start.** Importing the package does not import FastMCP, the MCP SDK, or
`langchain.mcp`; they are loaded when the first server is used.
