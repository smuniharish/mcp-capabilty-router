"""Rank capabilities by meaning as well as by words.

`QdrantRetriever` ranks with BM25 by default. Give it an embedder and it ranks
by meaning too, fusing both rankings, so requests that share no words with a
tool still find it. `LangChainEmbedder` wraps any LangChain embedding model;
subclass `Embedder` to use any other embedding service.

Requires the `langchain` extra and an embedding model, named as for
`langchain.embeddings.init_embeddings`:

    MCP_ROUTER_EXAMPLE_EMBEDDINGS=openai:text-embedding-3-small   # and OPENAI_API_KEY
"""

import asyncio
import os

from common import billing_server, crm_server, docs_server
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings

from mcp_capability_router import MCPRuntime, QdrantRetriever, RefreshPolicy
from mcp_capability_router.integrations.langchain import LangChainEmbedder

REQUESTS = (
    "give a customer their money back",
    "where are the setup instructions",
    "who is our contact at Acme",
)


async def main(embeddings: Embeddings) -> None:
    retriever = QdrantRetriever(embedder=LangChainEmbedder(embeddings))
    async with MCPRuntime(retriever=retriever) as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)
        for request in REQUESTS:
            matches = await runtime.retrieve(request, limit=2)
            print(f"{request!r}: {[match.capability_id for match in matches]}")


if __name__ == "__main__":
    asyncio.run(main(init_embeddings(os.environ["MCP_ROUTER_EXAMPLE_EMBEDDINGS"])))
