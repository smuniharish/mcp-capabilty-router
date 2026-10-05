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

## Keyword retrieval

`KeywordRetriever` is the default. It needs no model, no service, and no tuning, it
is deterministic, and it ranks tens of thousands of capabilities in milliseconds.

It splits names and identifiers into words, so `read_text_file`, `readTextFile`, and
`read-text-file` all contain `read`, `text`, and `file`. A query word matches a
capability word when it is that word, when it is a prefix of that word of at least 3
characters, or when both words share their first 4 or more characters. So `nav`
matches `navigate`, `navigation` matches `navigate`, and `files` matches `file`,
while `read` does not match `thread`. Common English stop words are ignored.

Each match is weighted by where it occurs and how complete it is:

| Field | Weight |
| --- | --- |
| Name or title | 3 |
| Tag | 2 |
| Description or resource URI | 1 |

A whole word counts fully. A prefix counts in proportion to the share of the word it
covers, and a shared stem in proportion to the share of both words it covers, so an
exact match always outranks a partial one in the same field. Each query word is then
weighted by how rare it is among the candidates, so distinctive words count more than
words that most capabilities share. Ties are broken by capability ID.

<!-- test -->
```python
import asyncio

from mcp_capability_router import KeywordRetriever, Tool


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
    retriever = KeywordRetriever()
    for query in ("read a file", "find files by name", "show what is in a directory"):
        ranked = await retriever.retrieve(query, CATALOG, limit=2)
        print(f"{query}: {[capability.name for capability in ranked]}")


asyncio.run(main())
```

```text
read a file: ['read_file', 'read_multiple_files']
find files by name: ['search_files', 'read_multiple_files']
show what is in a directory: ['list_directory']
```

Keyword retrieval matches words, not meanings: `find` does not match `search`. When
users phrase requests in words that tool descriptions do not use, use embedding
retrieval, or write descriptions with the words users say.

## Embedding retrieval

`EmbeddingRetriever` ranks by semantic similarity with any LangChain embedding model:

```python
from langchain.embeddings import init_embeddings

from mcp_capability_router import EmbeddingRetriever, MCPRuntime

runtime = MCPRuntime(
    retriever=EmbeddingRetriever(init_embeddings("openai:text-embedding-3-small"))
)
```

Each capability is embedded once, from its title, name, description, tags, and URI,
and embedded again only when that text changes. The vectors live in a LangChain
`InMemoryVectorStore` inside the retriever. Each query embeds the query text once.

`max_documents`, 50,000 by default, bounds the number of stored vectors. When it is
exceeded, the vectors of the capabilities that queries have not seen for the longest
time are dropped; the candidates of the current query are always kept.

### Rerank the best matches

Pass any LangChain document compressor, such as a cross-encoder or a provider
reranker, to re-rank the best `fetch_k` matches:

```python
retriever = EmbeddingRetriever(embeddings, reranker=reranker, fetch_k=30)
```

## Choose a retriever

| | `KeywordRetriever` | `EmbeddingRetriever` |
| --- | --- | --- |
| Matches | Words and identifiers | Meaning |
| Needs | Nothing | An embedding model |
| Cost per query | Microseconds to milliseconds, no I/O | One embedding call plus a vector search |
| Deterministic | Yes | As deterministic as the model |
| Best for | Well-named tools, tests, offline use, large catalogs | Natural-language requests, synonyms, many languages |

Both are measured in [Performance](performance.md). To combine rankings, or to rank
with a service of your own, implement the `CapabilityRetriever` contract; see
[Extending the router](extending.md#retrievers).

## Write capabilities that retrieve well

Retrieval can only use what servers describe. When you write MCP servers:

- Name tools after what they do, such as `search_customers` or `issue_refund`.
- Write a one-sentence description with the words users use.
- Add tags for the domain, such as `tags={"billing"}` in FastMCP.
- Give resources descriptive names and URIs.
