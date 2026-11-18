# Retrieval

Retrieval ranks the registry's capabilities against a request. It never calls a
server.

## Calls

```python
from mcp_capability_router import CapabilityType

tools = await runtime.retrieve("refund an invoice", type=CapabilityType.TOOL, limit=5)
tools = await runtime.query("refund an invoice", server_id="billing", limit=5)
routed = await runtime.route_tools("refund an invoice", limit=5)
```

- `type` and `server_id` filter candidates before ranking; use them when known.
- `query` and `route_tools` refresh servers with `on_query_miss` when nothing
  matches, then retrieve again.
- Results are best first and at most `limit` long; an empty list means no match.

## LoomRetriever, the default

`LoomRetriever` ranks with a RetrievalLoom engine.

| Need | Configuration |
| --- | --- |
| Deterministic, offline, no model | `LoomRetriever()`: BM25 in memory |
| Natural-language requests, synonyms | `LoomRetriever(embedder=embedder)`: BM25 and dense, fused by RRF |
| Best order among the matches | `reranker=...`, a RetrievalLoom `RerankerABC` such as a cross-encoder |
| Index kept across restarts | `resources=EngineResources(data_dir=Path(...))` |
| Shared index across processes | `components=Components(vector_store=QdrantVectorStore(...))`, `collection=...` |
| Other ranking methods, fusion, weights | `config=EngineConfig(...)` |

```python
from qdrant_client import AsyncQdrantClient
from retrievalloom import Components
from retrievalloom.index.vector import QdrantVectorStore

from mcp_capability_router import LoomRetriever, MCPRuntime

store = QdrantVectorStore(client=AsyncQdrantClient(url="http://localhost:6333"))
retriever = LoomRetriever(
    embedder=my_embedder,
    components=Components(vector_store=store),
    collection="support_capabilities",
)
runtime = MCPRuntime(retriever=retriever)
```

- An embedder subclasses `Embedder` with async `embed_documents` and
  `embed_query`. With the `langchain` extra, `LangChainEmbedder(embeddings)`
  wraps any LangChain embedding model.
- The retriever never closes components it is given; close them after the
  runtime.
- Give each catalog its own collection.
- The engine starts on the first query, in a second or two; reuse one runtime
  per process.
## How BM25 ranks

- Identifiers are split into words: `read_text_file` and `readTextFile` both
  contain `read`, `text`, and `file`. Plurals match their singular; words that
  share their first five letters match partly.
- Weights: name or title 3, tag 2, description or URI 1. Rare words count more.
- Equal scores order by capability ID, so rankings are deterministic.
- It matches words, not meanings: `find` does not match `search`. Add an
  embedder for meaning.

## Indexing

- Capabilities are indexed on first sight and again only when their text
  changes; a durable store that already holds them is not embedded again.
- `max_documents` (50,000) bounds the index; the least recently seen are evicted.
- Each query searches only its candidates.

## Improve results

1. Fix metadata at the source: tool names that say what they do, one-sentence
   descriptions with the users' words, and FastMCP `tags`.
2. Narrow candidates with `server_id` and `type`.
3. Raise `limit` so that the model can choose.
4. Add an embedder for hybrid ranking, and a reranker for the best order.