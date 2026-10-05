# Benchmarks

The benchmarks measure the router's own overhead with in-memory adapters, so the
numbers exclude network and server time. They are not part of the test suite.

```bash
uv run python benchmarks/bench_retrieval.py   # keyword and embedding retrieval
uv run python benchmarks/bench_runtime.py     # refresh and execute dispatch
```

`bench_retrieval.py` ranks synthetic tool catalogs of 100 to 100,000 capabilities
and reports the median latency of one query. The embedding benchmark uses a hash
function instead of a model, so it measures the vector search, not the embedding
model.

`bench_runtime.py` refreshes a server with 1,000 and 10,000 tools twice (the
second refresh finds nothing changed) and reports the median latency of
`MCPRuntime.execute` through the whole resilience pipeline.
