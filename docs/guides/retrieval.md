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

## QdrantRetriever

`QdrantRetriever` is the default retriever. It ranks with
[Qdrant](https://qdrant.tech): BM25 on words, dense vectors from an embedding model,
or both, fused.

| Need | Configuration |
| --- | --- |
| Deterministic ranking with no model and no service | `QdrantRetriever()`: BM25 in an in-process collection |
| Natural-language requests and synonyms | `QdrantRetriever(embedder=embedder)`: hybrid BM25 and dense |
| Meaning only | `QdrantRetriever(embedder=embedder, mode="dense")` |
| One index shared by every process | `QdrantRetriever(client=AsyncQdrantClient(url=...))` |

### BM25

Without arguments, the retriever keeps an in-process Qdrant collection and ranks
with BM25. It needs no model, no service, and no tuning, and it is deterministic.

It splits names and identifiers into words, so `read_text_file`, `readTextFile`, and
`read-text-file` all contain `read`, `text`, and `file`. Plurals match their
singular, and words that share their first five letters match partly, so
`navigation` partly matches `navigate`. Common English stop words are ignored.

Each word is weighted by where it occurs:

| Field | Weight |
| --- | --- |
| Name or title | 3 |
| Tag | 2 |
| Description or resource URI | 1 |

Qdrant then weighs each word by its inverse document frequency, so distinctive words
count more than words that most capabilities share. Ties are broken by capability ID.

<!-- test -->
```python
import asyncio

from mcp_capability_router import QdrantRetriever, Tool


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
    retriever = QdrantRetriever()
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

Give the retriever an `Embedder` and it ranks by meaning as well. Qdrant fuses the
BM25 and dense rankings, with reciprocal rank fusion by default:

```python
from mcp_capability_router import Embedder, MCPRuntime, QdrantRetriever


class ServiceEmbedder(Embedder):
    async def embed_documents(self, texts):
        return await embedding_service.embed(list(texts))

    async def embed_query(self, text):
        [vector] = await embedding_service.embed([text])
        return vector


runtime = MCPRuntime(retriever=QdrantRetriever(embedder=ServiceEmbedder()))
```

With the `langchain` extra, `LangChainEmbedder` adapts any LangChain embedding model:

```python
from langchain.embeddings import init_embeddings

from mcp_capability_router import QdrantRetriever
from mcp_capability_router.integrations.langchain import LangChainEmbedder

embeddings = init_embeddings("openai:text-embedding-3-small")
retriever = QdrantRetriever(embedder=LangChainEmbedder(embeddings))
```

- `fusion="dbsf"` selects distribution-based score fusion instead; `rrf_k` sets the
  constant of reciprocal rank fusion.
- `prefetch_limit`, 50 by default, bounds how many matches each ranking contributes.
- Each capability is embedded from its title, name, description, tags, and URI
  (`document_text`), once, and again only when that text changes. Each query embeds
  the query text once.

### A Qdrant server

Give the retriever an `AsyncQdrantClient` to keep the collection in a Qdrant server.
Every process of a service then ranks against the same index, and capabilities that
the collection already holds are not embedded again, even after a restart:

```python
from qdrant_client import AsyncQdrantClient

from mcp_capability_router import QdrantRetriever

client = AsyncQdrantClient(url="http://localhost:6333")
retriever = QdrantRetriever(
    embedder=embedder,
    client=client,
    collection_name="support_capabilities",
)
```

- Give each catalog its own collection: capability IDs identify the points.
- The retriever closes only a client that it created; close a client of your own
  after the runtime.
- `max_points`, 50,000 by default, bounds the indexed capabilities. When it is
  exceeded, the capabilities that queries have not seen for the longest time are
  dropped; the candidates of the current query are always kept.
- Each query searches only its candidates, filtered in Qdrant.

## LangChain vector stores

With the `langchain` extra, `VectorStoreRetriever` ranks with any LangChain
`VectorStore` instead of Qdrant, and can re-rank the best `fetch_k` matches with any
LangChain document compressor, such as a cross-encoder or a provider reranker:

```python
from mcp_capability_router.integrations.langchain import VectorStoreRetriever

retriever = VectorStoreRetriever(embeddings, reranker=reranker, fetch_k=30)
retriever = VectorStoreRetriever(vector_store=store)
```

`max_documents`, 50,000 by default, bounds the stored vectors as `max_points` does.

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