# Benchmarks

The benchmarks measure the router's own overhead with in-memory adapters, so the
numbers exclude network and server time. They are not part of the test suite.

```bash
uv run python benchmarks/bench_retrieval.py   # start, indexing, and query latency of LoomRetriever
uv run python benchmarks/bench_runtime.py     # refresh and execute dispatch
```

`bench_retrieval.py` ranks synthetic tool catalogs of 100 to 10,000 capabilities
in the lexical (BM25) and hybrid modes. It reports the RetrievalLoom engine's cold
start, the first query, which indexes the catalog, and the median latency of the
queries that follow. The hybrid mode uses a hash function instead of a model, so it
measures the retriever, not the embedding model. Set
`MCP_ROUTER_EXAMPLE_EMBEDDINGS`, as for the examples, such as
`sentence-transformers:models/bge-m3` with the `models` dependency group, to add a
mode with a real embedding model on catalogs of 100 and 1,000 capabilities.

`bench_runtime.py` refreshes a server with 1,000 and 10,000 tools twice (the
second refresh finds nothing changed) and reports the median latency of
`MCPRuntime.execute` through the whole resilience pipeline.