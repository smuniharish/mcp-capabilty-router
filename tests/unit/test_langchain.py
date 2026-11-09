"""The LangChain integration: tools, middleware, embeddings, and vector stores."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import pytest
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRequest, ToolCallRequest
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore
from mcp import types
from pydantic import Field

from mcp_capability_router import (
    CapabilityRetriever,
    ConfigurationError,
    MCPRuntime,
    QdrantRetriever,
    RefreshPolicy,
    RoutedTool,
    ServerConnectionError,
    Tool,
)
from mcp_capability_router.integrations.langchain import (
    CapabilityRoutingMiddleware,
    LangChainEmbedder,
    VectorStoreRetriever,
    _latest_user_text,
    mcp_client_tools,
    to_langchain_tool,
)
from tests.langchain_support import ScriptedChatModel, tool_messages
from tests.support import (
    FakeAdapter,
    capability_ids,
    mcp_tool,
    resource,
    tool,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterable, Sequence

    from langchain_core.callbacks import Callbacks

SEARCH_SCHEMA = {"type": "object", "properties": {"q": {"type": "string"}}}
VOCABULARY = ("read", "file", "send", "email", "weather", "forecast", "notes")


def crm() -> FakeAdapter:
    return FakeAdapter(
        tools=[
            mcp_tool("search", "Search customer records", input_schema=SEARCH_SCHEMA),
            mcp_tool("delete", "Delete a customer record"),
        ]
    )


def billing() -> FakeAdapter:
    return FakeAdapter(tools=[mcp_tool("search", "Search invoices", input_schema=SEARCH_SCHEMA)])


@pytest.fixture
async def runtime() -> AsyncIterator[MCPRuntime]:
    async with MCPRuntime() as instance:
        policy = RefreshPolicy(on_register=True)
        await instance.register_server("crm", crm, refresh=policy)
        await instance.register_server("billing", billing, refresh=policy)
        yield instance


def tool_call(name: str, args: dict[str, Any], call_id: str = "call-1") -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class StubRuntime(MCPRuntime):
    """A runtime whose tool calls return or raise a scripted value."""

    def __init__(self, outcome: Any) -> None:
        super().__init__()
        self.outcome = outcome
        self.received: list[Any] = []

    async def execute(self, capability_id: str, arguments: Any = None) -> Any:
        self.received.append(arguments)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def routed(outcome: Any, capability: Tool | None = None) -> RoutedTool:
    capability = capability or tool("s", "answer", "Answer")
    return RoutedTool(capability.name, capability, StubRuntime(outcome))


class TestToLangChainTool:
    def test_rejects_other_objects(self) -> None:
        with pytest.raises(ConfigurationError, match="is not a RoutedTool"):
            to_langchain_tool(object())  # type: ignore[arg-type]

    async def test_describes_the_routed_tool(self, runtime: MCPRuntime) -> None:
        converted = to_langchain_tool(await runtime.tool("crm:tool:search"), name="crm_search")
        assert (converted.name, converted.description) == ("crm_search", "Search customer records")
        assert converted.metadata == {"capability_id": "crm:tool:search", "server_id": "crm"}
        assert converted.args_schema == SEARCH_SCHEMA

    async def test_converts_every_mcp_content_type(self) -> None:
        result = CallToolResult(
            content=[
                types.TextContent(type="text", text="hello"),
                types.ImageContent(type="image", data="aW1n", mime_type="image/png"),
                types.AudioContent(type="audio", data="YXVk", mime_type="audio/wav"),
                types.ResourceLink(
                    type="resource_link", uri="file:///a.png", name="a", mime_type="image/png"
                ),
                types.ResourceLink(type="resource_link", uri="file:///a.pdf", name="a"),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.BlobResourceContents(
                        uri="file:///b.png", blob="Yg==", mime_type="image/png"
                    ),
                ),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.BlobResourceContents(uri="file:///b.bin", blob="Yg=="),
                ),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(uri="file:///c.txt", text="notes"),
                ),
            ],
            structured_content={"answer": 42},
            meta=None,
        )
        message = await to_langchain_tool(routed(result)).ainvoke(tool_call("answer", {}))
        blocks = [
            {key: value for key, value in block.items() if key != "id"} for block in message.content
        ]
        assert blocks == [
            {"type": "text", "text": "hello"},
            {"type": "image", "base64": "aW1n", "mime_type": "image/png"},
            {"type": "file", "base64": "YXVk", "mime_type": "audio/wav"},
            {"type": "image", "url": "file:///a.png", "mime_type": "image/png"},
            {"type": "file", "url": "file:///a.pdf"},
            {"type": "image", "base64": "Yg==", "mime_type": "image/png"},
            {"type": "file", "base64": "Yg==", "mime_type": "application/octet-stream"},
            {"type": "text", "text": "notes"},
        ]
        assert message.artifact == {"answer": 42}

    @pytest.mark.parametrize(
        ("outcome", "content", "artifact"),
        [
            ("plain", "plain", None),
            ({"tool": "x"}, "{'tool': 'x'}", {"tool": "x"}),
            (42, "42", 42),
        ],
    )
    async def test_other_results(self, outcome: Any, content: str, artifact: Any) -> None:
        message = await to_langchain_tool(routed(outcome)).ainvoke(tool_call("answer", {}))
        assert (message.content, message.artifact) == (content, artifact)

    async def test_unknown_content_blocks_become_text(self) -> None:
        result = CallToolResult(content=["odd"], structured_content=None, meta=None)  # type: ignore[list-item]
        message = await to_langchain_tool(routed(result)).ainvoke(tool_call("answer", {}))
        assert [block["text"] for block in message.content] == ["odd"]

    async def test_reports_router_errors_to_the_model(self, runtime: MCPRuntime) -> None:
        adapter = await runtime._servers["crm"].handle.adapter()
        adapter.failures["call_tool"] = [ServerConnectionError("crm is down")]  # type: ignore[attr-defined]
        converted = to_langchain_tool(await runtime.tool("crm:tool:search"))
        message = await converted.ainvoke(tool_call("search", {"q": "acme"}))
        assert message.status == "error"
        assert message.content == "ServerConnectionError: crm is down"

    @pytest.mark.parametrize(
        ("note", "content"),
        [
            (
                "call_tool on server 's' exceeded the operation timeout of 1s",
                "TimeoutError: call_tool on server 's' exceeded the operation timeout of 1s",
            ),
            (None, "TimeoutError"),
        ],
    )
    async def test_reports_timeouts_to_the_model(self, note: str | None, content: str) -> None:
        error = TimeoutError()
        if note is not None:
            error.add_note(note)
        message = await to_langchain_tool(routed(error)).ainvoke(tool_call("answer", {}))
        assert message.status == "error"
        assert message.content == content

    async def test_passes_arguments_named_like_langchain_parameters(self) -> None:
        schema = {
            "type": "object",
            "properties": {
                name: {"type": "string"} for name in ("config", "run_manager", "callbacks", "q")
            },
        }
        handle = routed("ok", tool("s", "apply", "Apply", input_schema=schema))
        arguments = {"config": "c", "run_manager": "r", "callbacks": "b", "q": "x"}
        message = await to_langchain_tool(handle).ainvoke(tool_call("apply", arguments))
        assert message.content == "ok"
        assert handle.runtime.received == [arguments]  # type: ignore[attr-defined]


def gateway_server() -> FastMCP:
    server = FastMCP("demo")

    @server.tool
    def forecast(city: str) -> dict[str, str]:
        """Weather forecast for a city."""
        return {"city": city}

    @server.tool
    def fail(reason: str) -> str:
        """Always fail."""
        raise ValueError(reason)

    @server.tool(title="Silent")
    def silent() -> None:
        """"""

    return server


class TestMCPClientTools:
    async def test_wraps_the_tools_of_a_connected_client(self) -> None:
        async with Client(gateway_server()) as client:
            tools = {item.name: item for item in await mcp_client_tools(client)}
            assert sorted(tools) == ["fail", "forecast", "silent"]
            assert tools["silent"].description == "Silent"
            message = await tools["forecast"].ainvoke(tool_call("forecast", {"city": "Oslo"}))
            assert message.artifact == {"city": "Oslo"}
            failed = await tools["fail"].ainvoke(tool_call("fail", {"reason": "boom"}))
            assert failed.status == "error"
            assert "boom" in failed.content

    async def test_errors_without_text_are_named(self) -> None:
        class Silent:
            async def list_tools(self) -> list[types.Tool]:
                return [mcp_tool("quiet")]

            async def call_tool(self, *args: Any, **kwargs: Any) -> CallToolResult:
                return CallToolResult(content=[], structured_content=None, meta=None, is_error=True)

        [quiet] = await mcp_client_tools(Silent())  # type: ignore[arg-type]
        assert quiet.description == "quiet"
        message = await quiet.ainvoke(tool_call("quiet", {}))
        assert message.content == "tool 'quiet' reported an error"


class TestLatestUserText:
    def test_reads_the_latest_human_message(self) -> None:
        assert _latest_user_text([]) == ""
        assert _latest_user_text([AIMessage("only the model")]) == ""
        assert (
            _latest_user_text(
                [HumanMessage("old"), AIMessage("reply"), HumanMessage("new question")]
            )
            == "new question"
        )
        blocks = HumanMessage(
            content=[
                {"type": "text", "text": "find"},
                "invoices",
                {"type": "image", "url": "https://example.com/x.png"},
            ]
        )
        assert _latest_user_text([blocks]) == "find invoices"


class TestMiddleware:
    @pytest.mark.parametrize(
        ("options", "message"),
        [
            ({"limit": 0}, "limit"),
            ({"server_id": "bad id"}, "invalid server ID"),
            ({"where": 42}, "where"),
        ],
    )
    def test_rejects_invalid_options(
        self, runtime: MCPRuntime, options: dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ConfigurationError, match=message):
            CapabilityRoutingMiddleware(runtime, **options)

    async def test_routes_only_relevant_tools_with_qualified_names(
        self, runtime: MCPRuntime
    ) -> None:
        model = ScriptedChatModel(
            responses=[
                AIMessage(content="", tool_calls=[tool_call("crm_search", {"q": "acme"})]),
                AIMessage(content="Found acme."),
            ]
        )
        agent = create_agent(
            model, tools=[], middleware=[CapabilityRoutingMiddleware(runtime, limit=2)]
        )
        result = await agent.ainvoke({"messages": [HumanMessage("search for acme")]})
        assert model.calls[0] == ["billing_search", "crm_search"]
        [message] = tool_messages(result)
        assert message.content == "{'tool': 'search', 'arguments': {'q': 'acme'}}"
        assert result["messages"][-1].content == "Found acme."

    async def test_scoped_middleware_uses_plain_names_and_keeps_static_tools(
        self, runtime: MCPRuntime
    ) -> None:
        @lc_tool
        def search(q: str) -> str:
            """Search the web."""
            return q

        model = ScriptedChatModel(
            responses=[
                AIMessage(content="", tool_calls=[tool_call("delete", {})]),
                AIMessage(content="Deleted."),
            ]
        )
        agent = create_agent(
            model,
            tools=[search],
            middleware=[
                CapabilityRoutingMiddleware(
                    runtime, server_id="crm", where=lambda item: item.destructive
                )
            ],
        )
        result = await agent.ainvoke({"messages": [HumanMessage("search and delete")]})
        assert model.calls[0] == ["search", "delete"]
        [message] = tool_messages(result)
        assert message.content == "{'tool': 'delete', 'arguments': {}}"

    async def test_passes_through_requests_without_a_query_or_routed_tool(
        self, runtime: MCPRuntime
    ) -> None:
        middleware = CapabilityRoutingMiddleware(runtime)
        model = ScriptedChatModel(responses=[])
        request = ModelRequest(
            model=model,
            messages=[AIMessage("no user message")],
            tools=[],
            state={"messages": []},
            runtime=None,
        )
        seen: list[ModelRequest[Any]] = []

        async def handler(forwarded: ModelRequest[Any]) -> Any:
            seen.append(forwarded)
            return "response"

        assert await middleware.awrap_model_call(request, handler) == "response"
        assert seen == [request]
        unmatched = ModelRequest(
            model=model,
            messages=[HumanMessage("nothing here matches")],
            tools=[],
            state={"messages": []},
            runtime=None,
        )
        assert await middleware.awrap_model_call(unmatched, handler) == "response"
        assert seen[-1] is unmatched

        @lc_tool
        def static(value: str) -> str:
            """Return the value."""
            return value

        calls: list[ToolCallRequest] = []

        async def run(forwarded: ToolCallRequest) -> ToolMessage:
            calls.append(forwarded)
            return ToolMessage(content="ran", tool_call_id="call-1")

        known = ToolCallRequest(
            tool_call=tool_call("static", {"value": "x"}),  # type: ignore[arg-type]
            tool=static,
            state={},
            runtime=None,  # type: ignore[arg-type]
        )
        await middleware.awrap_tool_call(known, run)
        unknown = ToolCallRequest(
            tool_call=tool_call("crm_unknown", {}),  # type: ignore[arg-type]
            tool=None,
            state={},
            runtime=None,  # type: ignore[arg-type]
        )
        await middleware.awrap_tool_call(unknown, run)
        assert [call.tool for call in calls] == [static, None]

    async def test_reports_ambiguous_tool_names(self) -> None:
        async with MCPRuntime() as runtime:
            policy = RefreshPolicy(on_register=True)
            await runtime.register_server(
                "a", lambda: FakeAdapter(tools=[mcp_tool("b_x")]), refresh=policy
            )
            await runtime.register_server(
                "a_b", lambda: FakeAdapter(tools=[mcp_tool("x")]), refresh=policy
            )
            middleware = CapabilityRoutingMiddleware(runtime)
            request = ToolCallRequest(
                tool_call={"name": "a_b_x", "args": {}, "id": None, "type": "tool_call"},
                tool=None,
                state={},
                runtime=None,  # type: ignore[arg-type]
            )

            async def run(forwarded: ToolCallRequest) -> ToolMessage:
                raise AssertionError("must not run")

            message = await middleware.awrap_tool_call(request, run)
            assert isinstance(message, ToolMessage)
            assert message.status == "error"
            assert "ambiguous between servers: a, a_b" in str(message.content)


class WordEmbeddings(Embeddings):
    """Embeds texts as bags of known words, so similarity is word overlap."""

    def __init__(self) -> None:
        self.documents: list[str] = []
        self.queries: list[str] = []
        self.failures = 0

    @staticmethod
    def _vector(text: str) -> list[float]:
        words = set(re.findall(r"[a-z]+", text.lower()))
        return [1.0 if word in words else 0.0 for word in VOCABULARY] + [0.01]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.failures:
            self.failures -= 1
            msg = "rate limited"
            raise ConnectionError(msg)
        self.documents.extend(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return self._vector(text)


class ReverseReranker(BaseDocumentCompressor):
    """Reverses the order of the documents it receives."""

    received: list[int] = Field(default_factory=list)

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Callbacks | None = None,
    ) -> Sequence[Document]:
        self.received.append(len(documents))
        return list(reversed(documents))


def catalog() -> list[Tool]:
    return [
        tool("s", "read_file", "Read a file"),
        tool("s", "send_email", "Send an email"),
        tool("s", "forecast", "Weather forecast"),
    ]


class TestLangChainEmbedder:
    async def test_embeds_with_langchain_embeddings(self) -> None:
        embeddings = DeterministicFakeEmbedding(size=4)
        embedder = LangChainEmbedder(embeddings)
        assert embedder.embeddings is embeddings
        assert len(await embedder.embed_query("x")) == 4
        assert [len(vector) for vector in await embedder.embed_documents(("a", "b"))] == [4, 4]
        with pytest.raises(ConfigurationError, match="does not subclass Embeddings"):
            LangChainEmbedder(object())  # type: ignore[arg-type]

    async def test_powers_the_qdrant_retriever(self) -> None:
        retriever = QdrantRetriever(embedder=LangChainEmbedder(WordEmbeddings()), mode="dense")
        assert capability_ids(await retriever.retrieve("weather", catalog(), limit=1)) == [
            "s:tool:forecast"
        ]
        await retriever.close()


class TestVectorStoreRetriever:
    def test_implements_the_contract_and_validates_settings(self) -> None:
        assert isinstance(VectorStoreRetriever(WordEmbeddings()), CapabilityRetriever)
        for value in (0, -1, True, 1.5):
            with pytest.raises(ConfigurationError, match="fetch_k"):
                VectorStoreRetriever(WordEmbeddings(), fetch_k=value)  # type: ignore[arg-type]
            with pytest.raises(ConfigurationError, match="max_documents"):
                VectorStoreRetriever(WordEmbeddings(), max_documents=value)  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError, match="embeddings or a vector_store"):
            VectorStoreRetriever()
        with pytest.raises(ConfigurationError, match="VectorStore"):
            VectorStoreRetriever(vector_store=object())  # type: ignore[arg-type]
        with pytest.raises(ConfigurationError, match="Embeddings"):
            VectorStoreRetriever(object())  # type: ignore[arg-type]
        store = ExternalStore(WordEmbeddings())
        assert VectorStoreRetriever(vector_store=store).vector_store is store

    async def test_ranks_candidates_by_similarity(self) -> None:
        embeddings = WordEmbeddings()
        retriever = VectorStoreRetriever(embeddings)
        assert await retriever.retrieve("x", [], limit=3) == []
        assert embeddings.queries == []
        ranked = await retriever.retrieve("read a file", catalog(), limit=2)
        assert capability_ids(ranked)[0] == "s:tool:read_file"
        assert len(ranked) == 2
        with pytest.raises(ConfigurationError):
            await retriever.retrieve("x", catalog(), limit=0)

    async def test_only_current_candidates_are_returned(self) -> None:
        retriever = VectorStoreRetriever(WordEmbeddings())
        await retriever.retrieve("email", catalog(), limit=3)
        notes = [resource("s", "resource://notes", "notes", tags=frozenset({"read"}))]
        assert capability_ids(await retriever.retrieve("email", notes, limit=3)) == [
            "s:resource:resource://notes"
        ]

    async def test_capabilities_are_embedded_once_until_they_change(self) -> None:
        embeddings = WordEmbeddings()
        retriever = VectorStoreRetriever(embeddings)
        await retriever.retrieve("weather", catalog(), limit=1)
        await retriever.retrieve("email", catalog(), limit=1)
        assert len(embeddings.documents) == 3
        changed = [*catalog()[:2], tool("s", "forecast", "Weather forecast for a city")]
        await retriever.retrieve("weather", changed, limit=1)
        assert len(embeddings.documents) == 4

    async def test_reranker_reorders_the_fetched_matches(self) -> None:
        reranker = ReverseReranker()
        retriever = VectorStoreRetriever(WordEmbeddings(), reranker=reranker, fetch_k=3)
        ranked = await retriever.retrieve("read a file", catalog(), limit=1)
        assert reranker.received[-1] == 3
        assert capability_ids(ranked) != ["s:tool:read_file"]

    async def test_least_recently_seen_vectors_are_evicted(self) -> None:
        embeddings = WordEmbeddings()
        retriever = VectorStoreRetriever(embeddings, max_documents=2)
        first, second, third = catalog()
        await retriever.retrieve("x", [first, second], limit=2)
        await retriever.retrieve("x", [third], limit=1)
        assert set(retriever._texts) == {second.capability_id, third.capability_id}
        await retriever.retrieve("read", [first], limit=1)
        assert len(embeddings.documents) == 4
        crowded = VectorStoreRetriever(WordEmbeddings(), max_documents=1)
        assert len(await crowded.retrieve("x", catalog(), limit=3)) == 3
        assert len(crowded._texts) == 3

    async def test_failed_embedding_calls_leave_the_retriever_consistent(self) -> None:
        embeddings = WordEmbeddings()
        embeddings.failures = 1
        retriever = VectorStoreRetriever(embeddings, max_documents=1)
        first, second, third = catalog()
        with pytest.raises(ConnectionError, match="rate limited"):
            await retriever.retrieve("read", [first], limit=1)
        assert retriever._seen == {}
        for _ in range(2):
            ranked = await retriever.retrieve("email", [second, third], limit=1)
            assert capability_ids(ranked) == ["s:tool:send_email"]
        assert set(retriever._texts) == set(retriever._seen)
        ranked = await retriever.retrieve("read", [first], limit=1)
        assert capability_ids(ranked) == ["s:tool:read_file"]


class ExternalStore(VectorStore):
    """A vector store that is not an `InMemoryVectorStore`, backed by one."""

    def __init__(self, embeddings: Embeddings, *, lookups: bool = True) -> None:
        self.inner = InMemoryVectorStore(embeddings)
        self.lookups = lookups
        self.searches: list[int] = []

    @property
    def embeddings(self) -> Embeddings:
        return self.inner.embeddings

    @classmethod
    def from_texts(cls, *args: Any, **kwargs: Any) -> ExternalStore:
        raise NotImplementedError

    def similarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        raise NotImplementedError

    async def aadd_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        return await self.inner.aadd_documents(documents, **kwargs)

    async def adelete(self, ids: list[str] | None = None, **kwargs: Any) -> bool | None:
        return await self.inner.adelete(ids)

    async def asimilarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        self.searches.append(k)
        return await self.inner.asimilarity_search(query, k=k)

    async def aget_by_ids(self, ids: Iterable[str], /) -> list[Document]:
        if not self.lookups:
            raise NotImplementedError
        # Some stores return more than was asked for; the extras must be ignored.
        return [*await self.inner.aget_by_ids(list(ids)), Document(id="x", page_content="")]


class TestPersistentVectorStores:
    async def test_a_restarted_retriever_reuses_stored_vectors(self) -> None:
        embeddings = WordEmbeddings()
        store = ExternalStore(embeddings)
        first = VectorStoreRetriever(vector_store=store)
        assert (await first.retrieve("send email", catalog(), limit=1))[0].name == "send_email"
        embedded = len(embeddings.documents)
        second = VectorStoreRetriever(vector_store=store)
        assert (await second.retrieve("read file", catalog(), limit=1))[0].name == "read_file"
        assert len(embeddings.documents) == embedded

    async def test_stores_without_lookups_re_embed(self) -> None:
        embeddings = WordEmbeddings()
        store = ExternalStore(embeddings, lookups=False)
        await VectorStoreRetriever(vector_store=store).retrieve("notes", catalog(), limit=1)
        embedded = len(embeddings.documents)
        await VectorStoreRetriever(vector_store=store).retrieve("notes", catalog(), limit=1)
        assert len(embeddings.documents) == 2 * embedded

    async def test_searches_widen_until_enough_candidates_match(self) -> None:
        store = ExternalStore(WordEmbeddings())
        retriever = VectorStoreRetriever(vector_store=store)
        others = [tool("other", f"weather_{index}", "weather forecast") for index in range(60)]
        await retriever.retrieve("weather", others, limit=1)
        wanted = catalog()
        store.searches.clear()
        found = await retriever.retrieve("weather forecast", wanted, limit=2)
        assert {capability.server_id for capability in found} <= {"s"}
        assert len(found) == 2
        assert len(store.searches) > 1
