"""Classification of failures for retries and circuit breakers.

The resilience pipeline uses `is_retryable` twice: as the default retry predicate
that the documentation recommends, and to decide whether a failure counts toward
the circuit breaker of a server. Failures that are not retryable prove that the
server answered, so they never open a circuit.
"""

from __future__ import annotations

from enum import StrEnum

from .errors import (
    AuthenticationError,
    AuthorizationError,
    CapabilityNotFoundError,
    CapabilityTypeError,
    ConfigurationError,
    InvalidRequestError,
    PromptRetrievalError,
    ProtocolError,
    RateLimitError,
    RefreshError,
    ResourceReadError,
    RuntimeClosedError,
    ServerConnectionError,
    ServerNotFoundError,
    ServerUnavailableError,
    ToolExecutionError,
)


class FailureCategory(StrEnum):
    """Semantic category of a failure."""

    CONNECTION_FAILURE = "connection_failure"
    """The server could not be reached, or the connection was lost."""

    TIMEOUT = "timeout"
    """The operation took longer than allowed."""

    AUTHENTICATION_FAILURE = "authentication_failure"
    """The server rejected the credentials."""

    AUTHORIZATION_FAILURE = "authorization_failure"
    """The client may not perform the operation."""

    RATE_LIMITED = "rate_limited"
    """The server throttled the client."""

    SERVER_UNAVAILABLE = "server_unavailable"
    """The server is temporarily unable to handle requests."""

    PROTOCOL_FAILURE = "protocol_failure"
    """The server violated the protocol, or the protocols are incompatible."""

    INVALID_REQUEST = "invalid_request"
    """The request or the configuration is invalid, or names a server or runtime
    that is not available."""

    CAPABILITY_NOT_FOUND = "capability_not_found"
    """The capability is not in the registry."""

    TOOL_EXECUTION_FAILURE = "tool_execution_failure"
    """A tool reported an error."""

    RESOURCE_READ_FAILURE = "resource_read_failure"
    """The server failed to read a resource."""

    PROMPT_RETRIEVAL_FAILURE = "prompt_retrieval_failure"
    """The server failed to render a prompt."""

    UNKNOWN = "unknown"
    """Any other exception."""


_NOT_RETRYABLE = frozenset(
    {
        FailureCategory.AUTHENTICATION_FAILURE,
        FailureCategory.AUTHORIZATION_FAILURE,
        FailureCategory.CAPABILITY_NOT_FOUND,
        FailureCategory.INVALID_REQUEST,
        FailureCategory.PROTOCOL_FAILURE,
        FailureCategory.TOOL_EXECUTION_FAILURE,
    }
)

_CATEGORIES: tuple[tuple[type[BaseException], FailureCategory], ...] = (
    (AuthenticationError, FailureCategory.AUTHENTICATION_FAILURE),
    (AuthorizationError, FailureCategory.AUTHORIZATION_FAILURE),
    (RateLimitError, FailureCategory.RATE_LIMITED),
    (ServerUnavailableError, FailureCategory.SERVER_UNAVAILABLE),
    (ProtocolError, FailureCategory.PROTOCOL_FAILURE),
    (InvalidRequestError, FailureCategory.INVALID_REQUEST),
    (ConfigurationError, FailureCategory.INVALID_REQUEST),
    (ServerNotFoundError, FailureCategory.INVALID_REQUEST),
    (CapabilityTypeError, FailureCategory.INVALID_REQUEST),
    (RuntimeClosedError, FailureCategory.INVALID_REQUEST),
    (CapabilityNotFoundError, FailureCategory.CAPABILITY_NOT_FOUND),
    (ToolExecutionError, FailureCategory.TOOL_EXECUTION_FAILURE),
    (ResourceReadError, FailureCategory.RESOURCE_READ_FAILURE),
    (PromptRetrievalError, FailureCategory.PROMPT_RETRIEVAL_FAILURE),
    (ServerConnectionError, FailureCategory.CONNECTION_FAILURE),
    (ConnectionError, FailureCategory.CONNECTION_FAILURE),
    (TimeoutError, FailureCategory.TIMEOUT),
)


def categorize_failure(error: BaseException) -> FailureCategory:
    """Return the semantic category of `error`.

    A `RefreshError` is categorized by the error that made its discovery fail.

    Args:
        error: The exception to categorize.

    Returns:
        The category; `FailureCategory.UNKNOWN` for unrecognized exceptions.
    """
    if isinstance(error, RefreshError) and error.__cause__ is not None:
        return categorize_failure(error.__cause__)
    for kind, category in _CATEGORIES:
        if isinstance(error, kind):
            return category
    return FailureCategory.UNKNOWN


def is_retryable(error: BaseException) -> bool:
    """Return whether retrying the operation that raised `error` can succeed.

    Cancellation and process-control exceptions are never retryable. Neither are
    authentication, authorization, invalid-request, capability-not-found, protocol,
    and tool-execution failures, nor requests for a server or runtime that is
    closed: repeating the same request fails the same way, and a tool may have
    side effects. Every other failure, including unrecognized exceptions, is
    retryable.

    Use it as the predicate of a `tenacity` retry policy:

    ```python
    from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt

    retry = AsyncRetrying(
        stop=stop_after_attempt(3), retry=retry_if_exception(is_retryable)
    )
    ```

    Args:
        error: The exception to classify.

    Returns:
        `True` if the operation may be retried.
    """
    if not isinstance(error, Exception):
        return False
    return categorize_failure(error) not in _NOT_RETRYABLE
