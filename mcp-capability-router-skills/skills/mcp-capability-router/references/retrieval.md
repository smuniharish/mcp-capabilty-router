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

## QdrantRetriever, the default

| Need | Configuration |
| --- | --- |
| Deterministic, offline, no model | `QdrantRetriever()`: BM25 in an in-process collection |
| Natural-language requests, synonyms | `QdrantRetriever(embedder=embedder)`: hybrid BM25 and dense |
| Meaning only | `mode="dense"` with an embedder |
| Shared index across processes | `client=AsyncQdrantClient(url=...)`, `collection_name=...` |
| Fusion | `fusion="rrf"` (default, `rrf_k`) or `"dbsf"`; `prefetch_limit` per ranking |

```python
from qdrant_client import AsyncQdrantClient

from mcp_capability_router import MCPRuntime, QdrantRetriever

retriever = QdrantRetriever(
    embedder=my_embedder,
    client=AsyncQdrantClient(url="http://localhost:6333"),
    collection_name="support_capabilities",
)
runtime = MCPRuntime(retriever=retriever)
```

- An embedder subclasses `Embedder` with async `embed_documents` and
  `embed_query`. With the `langchain` extra, `LangChainEmbedder(embeddings)`
  wraps any LangChain embedding model.
- The retriever closes only a client it created; close shared clients after the
  runtime.
- Give each catalog its own collection.

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
  changes; an external collection that already holds them is not embedded again.
- `max_points` (50,000) bounds the index; the least recently seen are evicted.
- Each query searches only its candidates.

## Improve results

1. Fix metadata at the source: tool names that say what they do, one-sentence
   descriptions with the users' words, and FastMCP `tags`.
2. Narrow candidates with `server_id` and `type`.
3. Raise `limit` so that the model can choose.
4. Add an embedder for hybrid ranking.