"""Translation of FastMCP, MCP, and transport errors into router errors.

FastMCP and the MCP SDK take a noticeable time to import, and errors only need
translating once a client exists, so they are imported on first use.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Iterator
from typing import TYPE_CHECKING

from ..errors import (
    AuthenticationError,
    AuthorizationError,
    InvalidRequestError,
    MCPCapabilityRouterError,
    PromptRetrievalError,
    ProtocolError,
    RateLimitError,
    ResourceReadError,
    ServerConnectionError,
    ServerError,
    ServerUnavailableError,
    ToolExecutionError,
)

if TYPE_CHECKING:
    from mcp.shared.exceptions import MCPError


@functools.cache
def _codes() -> tuple[frozenset[int], frozenset[int], int, int]:
    from mcp import types

    invalid = frozenset(
        {
            types.INVALID_PARAMS,
            types.INVALID_REQUEST,
            types.METHOD_NOT_FOUND,
            types.URL_ELICITATION_REQUIRED,
        }
    )
    protocol = frozenset(
        {
            types.PARSE_ERROR,
            types.HEADER_MISMATCH,
            types.UNSUPPORTED_PROTOCOL_VERSION,
            types.MISSING_REQUIRED_CLIENT_CAPABILITY,
        }
    )
    return invalid, protocol, types.CONNECTION_CLOSED, types.REQUEST_TIMEOUT


def _causes(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _from_mcp_error(error: MCPError) -> Exception:
    invalid, protocol, connection_closed, request_timeout = _codes()
    code = error.error.code
    message = error.error.message
    if code in invalid:
        return InvalidRequestError(message)
    if code in protocol:
        return ProtocolError(message)
    if code == connection_closed:
        return ServerConnectionError(message)
    if code == request_timeout:
        return TimeoutError(message)
    return ServerError(message)


def _from_status(status: int, message: str) -> Exception:
    if status == 401:
        return AuthenticationError(message)
    if status == 403:
        return AuthorizationError(message)
    if status == 408:
        return TimeoutError(message)
    if status == 429:
        return RateLimitError(message)
    if status >= 500:
        return ServerUnavailableError(message)
    if status in {404, 405, 406, 415}:
        return ProtocolError(message)
    return InvalidRequestError(message)


def _translate_one(error: BaseException) -> Exception | None:
    import anyio
    import httpx2
    from fastmcp import exceptions as fastmcp_errors
    from mcp.shared.exceptions import MCPError

    match error:
        case MCPCapabilityRouterError():
            return error
        case fastmcp_errors.ToolError():
            return ToolExecutionError(str(error))
        case fastmcp_errors.ResourceError():
            return ResourceReadError(str(error))
        case fastmcp_errors.PromptError():
            return PromptRetrievalError(str(error))
        case fastmcp_errors.AuthorizationError():
            return AuthorizationError(str(error))
        case (
            fastmcp_errors.NotFoundError()
            | fastmcp_errors.ValidationError()
            | fastmcp_errors.DisabledError()
        ):
            return InvalidRequestError(str(error))
        case MCPError():
            return _from_mcp_error(error)
        case httpx2.HTTPStatusError():
            return _from_status(error.response.status_code, str(error))
        case httpx2.TimeoutException() | TimeoutError():
            return TimeoutError(str(error))
        case (
            httpx2.TransportError()
            | anyio.BrokenResourceError()
            | anyio.ClosedResourceError()
            | anyio.EndOfStream()
            | OSError()
        ):
            return ServerConnectionError(str(error) or type(error).__name__)
        case _:
            return None


def translate_error(error: Exception) -> Exception:
    """Return the router error that best describes a FastMCP or transport error.

    The cause chain of `error` is searched for the first recognized exception;
    unrecognized errors are returned unchanged.
    """
    for cause in _causes(error):
        translated = _translate_one(cause)
        if translated is not None:
            return translated
    return error


async def translated[T](awaitable: Awaitable[T]) -> T:
    """Await `awaitable`, translating the errors it raises."""
    try:
        return await awaitable
    except Exception as error:
        replacement = translate_error(error)
        if replacement is error:
            raise
        raise replacement from error
