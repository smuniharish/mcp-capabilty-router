# Benchmarks

The benchmarks measure the router's own overhead with in-memory adapters, so the
numbers exclude network and server time. They are not part of the test suite.

```bash
uv run python benchmarks/bench_retrieval.py   # indexing and query latency of QdrantRetriever
uv run python benchmarks/bench_runtime.py     # refresh and execute dispatch
```

`bench_retrieval.py` ranks synthetic tool catalogs of 100 to 10,000 capabilities
in the sparse (BM25) and hybrid modes. It reports the first query, which indexes
the catalog, and the median latency of the queries that follow. The hybrid mode
uses a hash function instead of a model, so it measures the retriever and Qdrant,
not the embedding model. It uses an in-process Qdrant collection; set
`MCP_ROUTER_BENCH_QDRANT_URL` to measure a Qdrant server instead.

`bench_runtime.py` refreshes a server with 1,000 and 10,000 tools twice (the
second refresh finds nothing changed) and reports the median latency of
`MCPRuntime.execute` through the whole resilience pipeline.
