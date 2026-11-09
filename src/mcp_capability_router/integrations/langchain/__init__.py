"""LangChain integration: tools, agent middleware, embeddings, and vector stores.

Needs the `langchain` extra: `pip install "mcp-capability-router[langchain]"`.

- `to_langchain_tool` turns a `RoutedTool` into a LangChain tool.
- `CapabilityRoutingMiddleware` gives a LangChain agent only the tools that match
  each turn.
- `LangChainEmbedder` lets `QdrantRetriever` embed with any LangChain
  `Embeddings`.
- `VectorStoreRetriever` ranks capabilities with any LangChain vector store.
- `mcp_client_tools` turns the tools of a connected FastMCP client, such as one
  connected to `MCPRuntime.as_mcp_server`, into LangChain tools.
"""

from __future__ import annotations

import asyncio
import heapq
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

try:
    from langchain.agents.middleware import (
        AgentMiddleware,
        ModelRequest,
        ModelResponse,
        ToolCallRequest,
    )
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
    from langchain_core.messages import AnyMessage, HumanMessage, ToolMessage
    from langchain_core.messages.content import (
        create_file_block,
        create_image_block,
        create_text_block,
    )
    from langchain_core.tools import BaseTool, StructuredTool, ToolException
    from langchain_core.vectorstores import InMemoryVectorStore, VectorStore
except ImportError as error:  # pragma: no cover - only without the extra
    msg = (
        "mcp_capability_router.integrations.langchain needs the langchain extra: "
        'pip install "mcp-capability-router[langchain]"'
    )
    raise ImportError(msg) from error

from fastmcp.client.client import CallToolResult
from mcp.types import (
    AudioContent,
    BlobResourceContents,
    ContentBlock,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
)

from ..._internal.naming import validate_limit, validate_positive, validate_server_id
from ...contracts import CapabilityRetriever
from ...errors import ConfigurationError, InvalidRequestError, MCPCapabilityRouterError
from ...retrieval import Embedder, document_text
from ...tools import RoutedTool

if TYPE_CHECKING:
    from fastmcp import Client
    from langchain_core.documents import BaseDocumentCompressor
    from langgraph.types import Command

    from ...models import Capability, Tool
    from ...runtime import MCPRuntime

__all__ = [
    "CapabilityRoutingMiddleware",
    "LangChainEmbedder",
    "VectorStoreRetriever",
    "mcp_client_tools",
    "to_langchain_tool",
]


def _describe(error: BaseException) -> str:
    detail = str(error) or "; ".join(getattr(error, "__notes__", ()))
    return f"{type(error).__name__}: {detail}" if detail else type(error).__name__


def _block(content: ContentBlock) -> dict[str, Any]:
    """Convert one MCP content block into a LangChain content block."""
    match content:
        case TextContent():
            return dict(create_text_block(text=content.text))
        case ImageContent():
            return dict(create_image_block(base64=content.data, mime_type=content.mime_type))
        case AudioContent():
            # Tool messages accept no audio blocks; a file block keeps the audio.
            return dict(create_file_block(base64=content.data, mime_type=content.mime_type))
        case ResourceLink():
            mime_type = content.mime_type or None
            create = (
                create_image_block if (mime_type or "").startswith("image/") else create_file_block
            )
            return dict(create(url=content.uri, mime_type=mime_type))
        case EmbeddedResource(resource=BlobResourceContents() as blob):
            mime_type = blob.mime_type or "application/octet-stream"
            create = create_image_block if mime_type.startswith("image/") else create_file_block
            return dict(create(base64=blob.blob, mime_type=mime_type))
        case EmbeddedResource():
            return dict(create_text_block(text=getattr(content.resource, "text", "")))
        case _:
            return dict(create_text_block(text=str(content)))


def _content_and_artifact(result: Any) -> tuple[Any, Any]:
    """Split a tool result into what the model sees and the structured artifact."""
    if isinstance(result, CallToolResult):
        return [_block(block) for block in result.content], result.structured_content
    if isinstance(result, str | list):
        return result, None
    return str(result), result


class _MCPTool(StructuredTool):
    """Passes the tool input to the coroutine as one `arguments` dictionary.

    LangChain passes tool arguments as keyword arguments, which would hand MCP
    arguments named like LangChain's own parameters, such as `config`,
    `run_manager`, or `callbacks`, to LangChain instead of the tool.
    """

    def _to_args_and_kwargs(
        self, tool_input: str | dict[str, Any], tool_call_id: str | None
    ) -> tuple[tuple[str, ...], dict[str, Any]]:
        _, arguments = super()._to_args_and_kwargs(tool_input, tool_call_id)
        return (), {"arguments": arguments}


def to_langchain_tool(tool: RoutedTool, *, name: str | None = None) -> StructuredTool:
    """Return a LangChain tool that calls `tool` through its runtime.

    The tool message content holds LangChain content blocks converted from the
    MCP content: text, images, audio, embedded resources, and resource links. The
    artifact holds the structured content, if the tool returns any. Router errors,
    tool errors, and timeouts reach the model as error tool messages, so the agent
    can recover instead of aborting the run.

    Args:
        tool: The routed tool, from `MCPRuntime.route_tools`, `resolve_tool`, or
            `tool`.
        name: The name shown to the model; `tool.name` by default.

    Raises:
        ConfigurationError: If `tool` is not a `RoutedTool`.
    """
    if not isinstance(tool, RoutedTool):
        msg = f"tool {tool!r} is not a RoutedTool"
        raise ConfigurationError(msg)

    async def call(arguments: dict[str, Any]) -> tuple[Any, Any]:
        try:
            result = await tool(arguments)
        except (MCPCapabilityRouterError, TimeoutError) as error:
            raise ToolException(_describe(error)) from error
        return _content_and_artifact(result)

    return _MCPTool(
        name=name or tool.name,
        description=tool.description,
        args_schema=dict(tool.input_schema),
        coroutine=call,
        response_format="content_and_artifact",
        handle_tool_error=True,
        metadata={"capability_id": tool.capability_id, "server_id": tool.server_id},
    )


async def mcp_client_tools(client: Client[Any]) -> list[BaseTool]:
    """Return LangChain tools for every tool of a connected FastMCP client.

    Use it to give an agent the tools of any MCP server, for example the router
    exposed with `MCPRuntime.as_mcp_server`. The client must stay connected while
    the tools are used. Tool errors reach the model as error tool messages.

    Example:
        ```python
        async with Client(runtime.as_mcp_server()) as client:
            tools = await mcp_client_tools(client)
            agent = create_agent(model, tools=tools)
        ```
    """
    definitions = await client.list_tools()

    def build(name: str) -> Callable[[dict[str, Any]], Awaitable[tuple[Any, Any]]]:
        async def call(arguments: dict[str, Any]) -> tuple[Any, Any]:
            result = await client.call_tool(name, arguments, raise_on_error=False)
            content, artifact = _content_and_artifact(result)
            if result.is_error:
                text = "\n".join(b["text"] for b in content if b.get("type") == "text")
                raise ToolException(text or f"tool {name!r} reported an error")
            return content, artifact

        return call

    return [
        _MCPTool(
            name=definition.name,
            description=definition.description or definition.title or definition.name,
            args_schema=dict(definition.input_schema),
            coroutine=build(definition.name),
            response_format="content_and_artifact",
            handle_tool_error=True,
        )
        for definition in definitions
    ]


def _latest_user_text(messages: Sequence[AnyMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            content = message.content
            if isinstance(content, str):
                return content
            parts = (
                block if isinstance(block, str) else str(block.get("text", ""))
                for block in content
                if isinstance(block, str)
                or (isinstance(block, Mapping) and block.get("type") == "text")
            )
            return " ".join(part for part in parts if part)
    return ""


class CapabilityRoutingMiddleware(AgentMiddleware):
    """Gives a LangChain agent only the MCP tools that are relevant to each turn.

    Before every model call, the middleware routes the latest user message with
    `MCPRuntime.route_tools` and adds the best matching tools to the call, next to
    the tools the agent was created with. Calls to those tools run through the
    runtime, so the resilience pipeline, interceptors, metrics, and health
    tracking apply. The model never sees the full catalog, however many servers
    and tools are registered.

    Failures of routed tools reach the model as error tool messages, so the agent
    can recover instead of aborting the run.

    Tool names are the MCP tool names when the middleware is limited to one
    server; otherwise they are prefixed with the server ID, as in
    `filesystem_read_text_file`, so tools of different servers never collide.

    The middleware is asynchronous; invoke the agent with `ainvoke` or `astream`.

    Example:
        ```python
        from langchain.agents import create_agent

        agent = create_agent(
            model,
            tools=[],
            middleware=[CapabilityRoutingMiddleware(runtime, limit=5)],
        )
        result = await agent.ainvoke({"messages": [{"role": "user", "content": "..."}]})
        ```
    """

    def __init__(
        self,
        runtime: MCPRuntime,
        *,
        limit: int = 5,
        server_id: str | None = None,
        where: Callable[[Tool], bool] | None = None,
    ) -> None:
        """Create the middleware.

        Args:
            runtime: The runtime that routes and calls the tools.
            limit: The maximum number of routed tools per model call.
            server_id: Route only the tools of this server.
            where: Route only the tools for which it returns `True`, for example
                `lambda tool: not tool.destructive` to keep tools that the server
                marks as destructive away from the model.

        Raises:
            ConfigurationError: If `limit`, `server_id`, or `where` is invalid.
        """
        super().__init__()
        self._runtime = runtime
        self._limit = validate_limit(limit)
        self._server_id = validate_server_id(server_id) if server_id is not None else None
        if where is not None and not callable(where):
            msg = f"where {where!r} is not callable"
            raise ConfigurationError(msg)
        self._where = where

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        """Add the tools that match the latest user message to the model call."""
        query = _latest_user_text(request.messages)
        if query:
            present = {tool.name for tool in request.tools if isinstance(tool, BaseTool)}
            routed = [
                to_langchain_tool(tool)
                for tool in await self._runtime.route_tools(
                    query, server_id=self._server_id, limit=self._limit, where=self._where
                )
                if tool.name not in present
            ]
            if routed:
                request = request.override(tools=[*request.tools, *routed])
        return await handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Run calls of routed tools through the runtime."""
        if request.tool is not None:
            return await handler(request)
        name = request.tool_call["name"]
        try:
            tool = await self._runtime.resolve_tool(
                name, server_id=self._server_id, where=self._where
            )
        except InvalidRequestError as error:
            return ToolMessage(
                content=str(error),
                tool_call_id=request.tool_call["id"] or "",
                name=name,
                status="error",
            )
        if tool is not None:
            request = request.override(tool=to_langchain_tool(tool))
        return await handler(request)


class LangChainEmbedder(Embedder):
    """Lets `QdrantRetriever` embed with any LangChain `Embeddings`.

    Example:
        ```python
        from langchain_openai import OpenAIEmbeddings

        retriever = QdrantRetriever(
            embedder=LangChainEmbedder(OpenAIEmbeddings(model="text-embedding-3-small"))
        )
        ```
    """

    def __init__(self, embeddings: Embeddings) -> None:
        """Wrap `embeddings`.

        Raises:
            ConfigurationError: If `embeddings` does not subclass `Embeddings`.
        """
        if not isinstance(embeddings, Embeddings):
            msg = f"embeddings {embeddings!r} does not subclass Embeddings"
            raise ConfigurationError(msg)
        self._embeddings = embeddings

    @property
    def embeddings(self) -> Embeddings:
        """The wrapped LangChain embeddings."""
        return self._embeddings

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed `texts` with `aembed_documents`."""
        return await self._embeddings.aembed_documents(list(texts))

    async def embed_query(self, text: str) -> list[float]:
        """Embed `text` with `aembed_query`."""
        return await self._embeddings.aembed_query(text)


def _capability_id(document: Document) -> str:
    return str(document.metadata.get("capability_id") or document.id or "")


class VectorStoreRetriever(CapabilityRetriever):
    """Ranks capabilities by semantic similarity in any LangChain vector store.

    Use it to keep capability vectors in a store that the deployment already
    runs, such as pgvector, Chroma, or Elasticsearch, or to re-rank matches with a
    LangChain document compressor, such as a cross-encoder. `QdrantRetriever`
    with a `LangChainEmbedder` is the default choice otherwise.

    Capabilities are embedded once and re-embedded only when their text changes;
    with a persistent store, capabilities that it already holds are not embedded
    again.

    Example:
        ```python
        from langchain_openai import OpenAIEmbeddings
        from langchain_postgres import PGVectorStore

        retriever = VectorStoreRetriever(vector_store=PGVectorStore.create_sync(...))
        runtime = MCPRuntime(retriever=retriever)
        ```
    """

    def __init__(
        self,
        embeddings: Embeddings | None = None,
        *,
        vector_store: VectorStore | None = None,
        reranker: BaseDocumentCompressor | None = None,
        fetch_k: int = 20,
        max_documents: int = 50_000,
    ) -> None:
        """Create a retriever.

        Args:
            embeddings: The embedding model; the `embeddings` of `vector_store`
                when `None`.
            vector_store: Where the capability vectors are stored; an
                `InMemoryVectorStore` of `embeddings` when `None`. The retriever
                adds, replaces, and deletes documents whose IDs are capability IDs,
                so give it a store, or a collection, of its own.
            reranker: An optional document compressor that re-ranks the matches.
            fetch_k: Number of matches handed to the reranker; ignored without one.
            max_documents: Number of capability vectors to keep. When exceeded, the
                vectors of the capabilities seen least recently are dropped; the
                candidates of the current query are always kept.

        Raises:
            ConfigurationError: If neither `embeddings` nor `vector_store` is
                given, or an argument is invalid.
        """
        self._fetch_k = validate_positive("fetch_k", fetch_k)
        self._max_documents = validate_positive("max_documents", max_documents)
        if vector_store is not None and not isinstance(vector_store, VectorStore):
            msg = f"vector_store {vector_store!r} does not subclass VectorStore"
            raise ConfigurationError(msg)
        if embeddings is not None and not isinstance(embeddings, Embeddings):
            msg = f"embeddings {embeddings!r} does not subclass Embeddings"
            raise ConfigurationError(msg)
        if vector_store is None:
            if embeddings is None:
                msg = "VectorStoreRetriever needs embeddings or a vector_store"
                raise ConfigurationError(msg)
            vector_store = InMemoryVectorStore(embeddings)
        self._store = vector_store
        self._reranker = reranker
        self._texts: dict[str, str] = {}
        self._seen: dict[str, int] = {}
        self._queries = 0
        self._lock = asyncio.Lock()

    @property
    def vector_store(self) -> VectorStore:
        """The vector store that holds the capability vectors."""
        return self._store

    async def retrieve(
        self, query: str, candidates: Sequence[Capability], *, limit: int
    ) -> list[Capability]:
        """Return at most `limit` of `candidates`, most similar to `query` first.

        Raises:
            ConfigurationError: If `limit` is not a positive integer.
        """
        validate_limit(limit)
        if not candidates:
            return []
        await self._index(candidates)
        by_id = {capability.capability_id: capability for capability in candidates}
        k = max(limit, self._fetch_k) if self._reranker is not None else limit
        documents = await self._search(query, by_id, k)
        if self._reranker is not None:
            documents = await self._reranker.acompress_documents(documents, query)
        ranked = (by_id.get(_capability_id(document)) for document in documents)
        return [capability for capability in ranked if capability is not None][:limit]

    async def _search(self, query: str, by_id: dict[str, Capability], k: int) -> Sequence[Document]:
        k = min(k, len(by_id))
        if isinstance(self._store, InMemoryVectorStore):
            return await self._store.asimilarity_search(
                query, k=k, filter=lambda document: document.id in by_id
            )
        # Vector stores filter by metadata in store-specific ways, so the search
        # oversamples and keeps the candidates, widening until enough are found or
        # the store has no more documents.
        fetch = min(max(k * 4, k + 16), len(self._texts))
        while True:
            documents = await self._store.asimilarity_search(query, k=fetch)
            matches = [doc for doc in documents if _capability_id(doc) in by_id]
            if len(matches) >= k or len(documents) < fetch or fetch >= len(self._texts):
                return matches[:k]
            fetch = min(fetch * 4, len(self._texts))

    async def _index(self, candidates: Sequence[Capability]) -> None:
        async with self._lock:
            self._queries += 1
            texts = {
                capability.capability_id: document_text(capability) for capability in candidates
            }
            await self._recover([key for key in texts if key not in self._texts])
            changed = {key: text for key, text in texts.items() if self._texts.get(key) != text}
            if changed:
                await self._store.aadd_documents(
                    [
                        Document(
                            id=capability_id,
                            page_content=text,
                            metadata={"capability_id": capability_id},
                        )
                        for capability_id, text in changed.items()
                    ],
                    ids=list(changed),
                )
                self._texts.update(changed)
            # Only stored capabilities are tracked, so a failed embedding call
            # leaves the retriever as it was.
            for capability_id in texts:
                self._seen[capability_id] = self._queries
            overflow = len(self._texts) - self._max_documents
            if overflow > 0:
                idle = [key for key, seen in self._seen.items() if seen < self._queries]
                stale = heapq.nsmallest(overflow, idle, key=self._seen.__getitem__)
                if stale:
                    await self._store.adelete(stale)
                for capability_id in stale:
                    del self._texts[capability_id]
                    del self._seen[capability_id]

    async def _recover(self, capability_ids: list[str]) -> None:
        """Learn the texts of capabilities that a persistent store already holds."""
        if not capability_ids or isinstance(self._store, InMemoryVectorStore):
            return
        try:
            documents = await self._store.aget_by_ids(capability_ids)
        except NotImplementedError:
            return
        for document in documents:
            capability_id = _capability_id(document)
            if capability_id in capability_ids:
                self._texts[capability_id] = document.page_content
                self._seen.setdefault(capability_id, 0)
