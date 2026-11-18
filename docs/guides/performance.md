# Performance

The router adds little to the cost of an MCP call: the network and the server
dominate. These measurements show the router's own overhead, with in-memory adapters
and no network.

## Benchmark results

Measured with CPython 3.12 on a laptop. Treat the numbers as indicative, and run the
benchmarks on your own hardware with `python benchmarks/bench_retrieval.py` and
`python benchmarks/bench_runtime.py` from the repository.

### Retrieval

Median latency of one query with `LoomRetriever` and its in-memory index, measured
with CPython 3.14 on Windows:

| Capabilities | BM25 | Hybrid |
| ---: | ---: | ---: |
| 100 | 18 ms | 30 ms |
| 1,000 | 24 ms | 62 ms |
| 10,000 | 60 ms | 210 ms |

The engine starts on the first query, which takes 1 to 2.5 s while RetrievalLoom
inspects the host. The first query over 10,000 capabilities also indexes them,
which takes about 10 s for BM25 and 22 s for hybrid ranking. Later queries index
only the capabilities that changed. The hybrid benchmark uses a hash `Embedder`
instead of a model, so it measures the search; a real embedding model adds one
embedding call per query, and one per new or changed capability. With `BAAI/bge-m3`
on a CPU, indexing 1,000 capabilities takes about 56 s and a query about 62 ms.

### Refresh and execution

| Measurement | 1,000 tools | 10,000 tools |
| --- | ---: | ---: |
| First refresh | 111 ms | 250 ms |
| Refresh with nothing changed | 19 ms | 324 ms |
| `execute` through the full pipeline, median | 5 ?s | 4 ?s |

## Tuning advice

**Narrow the candidates.** Retrieval time grows linearly with the number of
candidates. Pass `type` and `server_id` when you know them, and scope agents to the
servers they need. `LoomRetriever` indexes each capability once and again only
when its text changes, and searches only the candidates of each query.

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

**Embed once.** With an embedder, `LoomRetriever` embeds each capability once and
again only when its text changes. Keep one retriever per runtime, and size
`max_documents` to your catalog, so that capabilities are not evicted and embedded
again. Give it a `data_dir` or a durable vector store so that a restarted process
does not embed its catalog again.

**Cold start.** The RetrievalLoom engine starts with the first query, and takes a
second or two; create runtimes once per process, not per request. Importing the
package does not import LangChain, which is loaded only through
`mcp_capability_router.integrations.langchain`.
