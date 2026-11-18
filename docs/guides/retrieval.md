# Retrieval

Retrieval selects the capabilities that match a request. It reads the registry only
and never calls a server, so it is fast and safe to run before every model call.

## Retrieve and query

`retrieve` ranks the known capabilities and returns the best matches, best first:

```python
from mcp_capability_router import CapabilityType

tools = await runtime.retrieve(
    "create an invoice for a customer",
    type=CapabilityType.TOOL,
    server_id="billing",
    limit=5,
)
```

`type` and `server_id` narrow the candidates before ranking, and `limit` bounds the
result. `query` takes the same arguments and refreshes servers when nothing matches:
the servers named in `refresh_servers`, and the servers whose refresh policy sets
`on_query_miss`. See [Discovery and refresh](refresh.md#refresh-on-a-query-miss).
`route_tools` queries tools and returns them ready to call by any
[agent framework](integrations.md).

`where` accepts a predicate over a capability and filters before ranking. Servers
with open circuits are excluded by default; `include_unhealthy=True` explicitly
includes them. Retrieval predicates are not authorization checks: protect execution
with an interceptor as well.

## LoomRetriever

`LoomRetriever` is the default retriever. It ranks with a
[RetrievalLoom](https://pypi.org/project/retrievalloom/) engine: BM25 on words,
dense vectors from an embedding model, or both, fused, and optionally reranked.

| Need | Configuration |
| --- | --- |
| Deterministic ranking with no model and no service | `LoomRetriever()`: BM25 in memory |
| Natural-language requests and synonyms | `LoomRetriever(embedder=embedder)`: hybrid BM25 and dense |
| The best order among the matches | `LoomRetriever(embedder=embedder, reranker=reranker)` |
| An index kept across restarts | `LoomRetriever(resources=EngineResources(data_dir=...))` |
| One index shared by every process | `LoomRetriever(components=Components(vector_store=...))` |

The engine starts on the first query, which takes a second or two: RetrievalLoom
inspects the host before it serves. Create one retriever per process, through one
runtime, and close it with the runtime.

### BM25

Without arguments, the retriever keeps an in-memory index and ranks with BM25. It
needs no model, no service, and no tuning, and it is deterministic.

It splits names and identifiers into words, so `read_text_file`, `readTextFile`, and
`read-text-file` all contain `read`, `text`, and `file`. Plurals match their
singular, closely related word forms such as `navigation` and `navigate` match
partly, and common English stop words are ignored.

Descriptions, names, tags, and resource URIs all contribute to matching. Ties are
broken by capability ID.

<!-- test -->
```python
import asyncio

from mcp_capability_router import LoomRetriever, Tool


def tool(name: str, description: str, *tags: str) -> Tool:
    return Tool(
        capability_id=f"files:tool:{name}",
        server_id="files",
        name=name,
        description=description,
        tags=frozenset(tags),
    )


CATALOG = [
    tool("read_file", "Read the contents of one file.", "files"),
    tool("read_multiple_files", "Read several files at once.", "files"),
    tool("list_directory", "List the entries of a directory.", "directories"),
    tool("search_files", "Search for files whose names match a pattern.", "files"),
]


async def main() -> None:
    retriever = LoomRetriever()
    for query in (
        "read a file",
        "search files by name",
        "find files",
        "show what is in a directory",
    ):
        ranked = await retriever.retrieve(query, CATALOG, limit=2)
        print(f"{query}: {[capability.name for capability in ranked]}")
    await retriever.close()


asyncio.run(main())
```

```text
read a file: ['read_file', 'read_multiple_files']
search files by name: ['search_files', 'read_file']
find files: ['read_file', 'search_files']
show what is in a directory: ['list_directory']
```

BM25 matches words, not meanings: `find` does not match `search`, so `find files`
ranks by `files` alone. When users phrase requests in words that tool descriptions
do not use, add an embedder, or write descriptions with the words users say.

### Hybrid ranking

Give the retriever an `Embedder` to combine keyword and semantic ranking:

```python
from mcp_capability_router import Embedder, LoomRetriever, MCPRuntime


class ServiceEmbedder(Embedder):
    async def embed_documents(self, texts):
        return await embedding_service.embed(list(texts))

    async def embed_query(self, text):
        [vector] = await embedding_service.embed([text])
        return vector


runtime = MCPRuntime(retriever=LoomRetriever(embedder=ServiceEmbedder()))
```

With the `langchain` extra, `LangChainEmbedder` adapts any LangChain embedding model:

```python
from langchain.embeddings import init_embeddings

from mcp_capability_router import LoomRetriever
from mcp_capability_router.integrations.langchain import LangChainEmbedder

embeddings = init_embeddings("openai:text-embedding-3-small")
retriever = LoomRetriever(embedder=LangChainEmbedder(embeddings))
```

- Each capability is embedded from its title, name, description, tags, and URI
  (`document_text`), once, and again only when that text changes. Each query embeds
  the query text once.
- `fetch_limit`, 50 by default, bounds how many matches the engine returns before
  ties are broken.
- `config` replaces the whole RetrievalLoom `EngineConfig`, including the ranking
  methods, their fusion, and their weights.

### Reranking

Give the retriever a RetrievalLoom `RerankerABC` to reorder the fused matches with
a cross-encoder, such as RetrievalLoom's `FlashRankReranker`. The
[semantic retrieval example](../examples.md#semantic-retrieval) wraps a
sentence-transformers `CrossEncoder`, such as `BAAI/bge-reranker-v2-m3`:

```python
retriever = LoomRetriever(embedder=embedder, reranker=reranker)
```

A reranker scores each pair of query and capability, so it is slower than the
rankings it reorders and best kept to a small `fetch_limit`.

### A durable or shared index

`EngineResources` with a `data_dir` keeps the index in files. A restarted process
finds its capabilities unchanged and embeds none of them again:

```python
from pathlib import Path

from retrievalloom import EngineResources

retriever = LoomRetriever(
    embedder=embedder,
    resources=EngineResources(data_dir=Path("var/capability-index")),
)
```

RetrievalLoom `Components` replace the engine's stores, for example with a Qdrant
server that every process of a service ranks against:

```python
from qdrant_client import AsyncQdrantClient
from retrievalloom import Components
from retrievalloom.index.vector import QdrantVectorStore

store = QdrantVectorStore(client=AsyncQdrantClient(url="http://localhost:6333"))
retriever = LoomRetriever(
    embedder=embedder,
    components=Components(vector_store=store),
    collection="support_capabilities",
)
```

- Give each catalog its own `collection`: capability IDs identify the documents.
- The retriever never closes components it is given; close them after the runtime.
- `max_documents`, 50,000 by default, bounds the indexed capabilities. When it is
  exceeded, the capabilities that queries have not seen for the longest time are
  dropped; the candidates of the current query are always kept.
- Each query searches only its candidates.
## LangChain vector stores

With the `langchain` extra, `VectorStoreRetriever` ranks with any LangChain
`VectorStore` instead of RetrievalLoom, and can re-rank the best `fetch_k` matches with any
LangChain document compressor, such as a cross-encoder or a provider reranker:

```python
from mcp_capability_router.integrations.langchain import VectorStoreRetriever

retriever = VectorStoreRetriever(embeddings, reranker=reranker, fetch_k=30)
retriever = VectorStoreRetriever(vector_store=store)
```

`max_documents`, 50,000 by default, bounds the stored vectors as it does for `LoomRetriever`.

## Your own ranking

To rank with a service of your own, subclass `CapabilityRetriever`; see
[Extending the router](extending.md#retrievers). Both retrievers are measured in
[Performance](performance.md).

## Write capabilities that retrieve well

Retrieval can only use what servers describe. When you write MCP servers:

- Name tools after what they do, such as `search_customers` or `issue_refund`.
- Write a one-sentence description with the words users use.
- Add tags for the domain, such as `tags={"billing"}` in FastMCP.
- Give resources descriptive names and URIs.