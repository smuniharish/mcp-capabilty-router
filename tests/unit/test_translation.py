from __future__ import annotations

import anyio
import httpx2
import pytest
from fastmcp import exceptions as fastmcp_errors
from mcp import types
from mcp.shared.exceptions import MCPError

from mcp_capability_router import (
    AuthenticationError,
    AuthorizationError,
    InvalidRequestError,
    PromptRetrievalError,
    ProtocolError,
    RateLimitError,
    ResourceReadError,
    ServerConnectionError,
    ServerError,
    ServerUnavailableError,
    ToolExecutionError,
)
from mcp_capability_router._internal.translation import translate_error, translated


def status_error(status: int) -> httpx2.HTTPStatusError:
    request = httpx2.Request("POST", "https://example.com/mcp")
    response = httpx2.Response(status, request=request)
    return httpx2.HTTPStatusError(
        f"status {status}", request=request, response=response
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (fastmcp_errors.ToolError("t"), ToolExecutionError),
        (fastmcp_errors.ResourceError("r"), ResourceReadError),
        (fastmcp_errors.PromptError("p"), PromptRetrievalError),
        (fastmcp_errors.AuthorizationError("a"), AuthorizationError),
        (fastmcp_errors.NotFoundError("n"), InvalidRequestError),
        (fastmcp_errors.ValidationError("v"), InvalidRequestError),
        (fastmcp_errors.DisabledError("d"), InvalidRequestError),
        (MCPError(types.INVALID_PARAMS, "bad"), InvalidRequestError),
        (MCPError(types.METHOD_NOT_FOUND, "no"), InvalidRequestError),
        (MCPError(types.PARSE_ERROR, "parse"), ProtocolError),
        (MCPError(types.UNSUPPORTED_PROTOCOL_VERSION, "old"), ProtocolError),
        (MCPError(types.CONNECTION_CLOSED, "closed"), ServerConnectionError),
        (MCPError(types.REQUEST_TIMEOUT, "slow"), TimeoutError),
        (MCPError(types.INTERNAL_ERROR, "oops"), ServerError),
        (status_error(401), AuthenticationError),
        (status_error(403), AuthorizationError),
        (status_error(408), TimeoutError),
        (status_error(429), RateLimitError),
        (status_error(503), ServerUnavailableError),
        (status_error(404), ProtocolError),
        (status_error(400), InvalidRequestError),
        (httpx2.ReadTimeout("slow"), TimeoutError),
        (TimeoutError("slow"), TimeoutError),
        (httpx2.ConnectError("refused"), ServerConnectionError),
        (anyio.BrokenResourceError(), ServerConnectionError),
        (anyio.ClosedResourceError(), ServerConnectionError),
        (anyio.EndOfStream(), ServerConnectionError),
        (FileNotFoundError("missing"), ServerConnectionError),
    ],
)
def test_translates_known_errors(error: Exception, expected: type[Exception]) -> None:
    translated_error = translate_error(error)
    assert type(translated_error) is expected
    assert str(translated_error)


def test_router_errors_and_unknown_errors_pass_through() -> None:
    error = ToolExecutionError("x")
    assert translate_error(error) is error
    unknown = KeyError("x")
    assert translate_error(unknown) is unknown


def test_searches_the_cause_chain_and_survives_cycles() -> None:
    def connect() -> None:
        try:
            raise httpx2.ConnectError("refused")
        except httpx2.ConnectError as cause:
            raise RuntimeError("Client failed to connect") from cause

    with pytest.raises(RuntimeError) as raised:
        connect()
    assert isinstance(translate_error(raised.value), ServerConnectionError)

    first, second = RuntimeError("a"), RuntimeError("b")
    first.__context__ = second
    second.__context__ = first
    assert translate_error(first) is first


async def test_translated_awaits_and_rewrites_errors() -> None:
    async def value() -> int:
        return 3

    async def failing() -> None:
        raise fastmcp_errors.ToolError("boom")

    async def unknown() -> None:
        raise KeyError("x")

    assert await translated(value()) == 3
    with pytest.raises(ToolExecutionError, match="boom") as raised:
        await translated(failing())
    assert isinstance(raised.value.__cause__, fastmcp_errors.ToolError)
    with pytest.raises(KeyError):
        await translated(unknown())
