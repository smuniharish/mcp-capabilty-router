"""Rank capabilities by meaning with any LangChain embedding model.

`EmbeddingRetriever` embeds every capability once, keeps the vectors in a
LangChain `InMemoryVectorStore`, and ranks candidates by similarity, so requests
that share no words with a tool still find it.

Requires an embedding model, named as for `langchain.embeddings.init_embeddings`:

    MCP_ROUTER_EXAMPLE_EMBEDDINGS=openai:text-embedding-3-small   # and OPENAI_API_KEY
"""

import asyncio
import os

from common import billing_server, crm_server, docs_server
from langchain.embeddings import init_embeddings
from langchain_core.embeddings import Embeddings

from mcp_capability_router import EmbeddingRetriever, MCPRuntime, RefreshPolicy

REQUESTS = (
    "give a customer their money back",
    "where are the setup instructions",
    "who is our contact at Acme",
)


async def main(embeddings: Embeddings) -> None:
    async with MCPRuntime(retriever=EmbeddingRetriever(embeddings)) as runtime:
        policy = RefreshPolicy(on_register=True)
        await runtime.register_mcp("crm", crm_server(), refresh=policy)
        await runtime.register_mcp("billing", billing_server(), refresh=policy)
        await runtime.register_mcp("docs", docs_server(), refresh=policy)
        for request in REQUESTS:
            matches = await runtime.retrieve(request, limit=2)
            print(f"{request!r}: {[match.capability_id for match in matches]}")


if __name__ == "__main__":
    asyncio.run(main(init_embeddings(os.environ["MCP_ROUTER_EXAMPLE_EMBEDDINGS"])))
