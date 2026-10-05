# Retrieval

Retrieval ranks the registry's capabilities against a request. It never calls a
server.

## Calls

```python
from mcp_capability_router import CapabilityType

tools = await runtime.retrieve("refund an invoice", type=CapabilityType.TOOL, limit=5)
tools = await runtime.query("refund an invoice", server_id="billing", limit=5)
```

- `type` and `server_id` filter candidates before ranking; use them when known.
- `query` refreshes servers with `on_query_miss`, or those in `refresh_servers`, when
  nothing matches, then retrieves again.
- Results are best first and at most `limit` long; an empty list means no match.

## Choose a retriever

| Need | Retriever |
| --- | --- |
| Deterministic, offline, no model, large catalogs | `KeywordRetriever()` (the default) |
| Natural-language requests, synonyms, other languages | `EmbeddingRetriever(embeddings)` |
| Both | A custom retriever that fuses both rankings; see [extensions.md](extensions.md) |

```python
from langchain.embeddings import init_embeddings

from mcp_capability_router import EmbeddingRetriever, MCPRuntime

runtime = MCPRuntime(
    retriever=EmbeddingRetriever(init_embeddings("openai:text-embedding-3-small"))
)
```

## How KeywordRetriever ranks

- Names and identifiers are split into words: `read_text_file`, `readTextFile`, and
  `read-text-file` all contain `read`, `text`, and `file`.
- A query word matches a capability word when it is that word, a prefix of it (3+
  characters), or shares its first 4+ characters. `read` does not match `thread`.
- Weights: name or title 3, tag 2, description or URI 1. Exact words count fully;
  prefixes and shared stems count in proportion to how much of the words they cover.
- Rare query words count more (inverse document frequency); ties break by capability
  ID; stop words are ignored.
- It matches words, not meanings: `find` does not match `search`.

## How EmbeddingRetriever ranks

- Embeds each capability's title, name, description, tags, and URI once, and again
  only when that text changes; vectors live in a LangChain `InMemoryVectorStore`.
- One embedding call per query.
- `reranker` takes any LangChain `BaseDocumentCompressor`; it re-ranks the best
  `fetch_k` matches.
- `max_documents` (50,000) bounds stored vectors; the least recently seen are evicted.

## Improve results

1. Fix metadata at the source: tool names that say what they do, one-sentence
   descriptions with the users' words, and FastMCP `tags`.
2. Narrow candidates with `server_id` and `type`.
3. Raise `limit` so that the model can choose.
4. Switch to, or fuse with, embeddings.
