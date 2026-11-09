"""Resilience settings and the classification of failures.

`ResiliencePolicy` configures how server operations are protected: timeouts,
retries, rate limits, circuit breakers, and concurrency. The runtime applies one
policy to every server and accepts a replacement per server.

The resilience pipeline uses `is_retryable` twice: as the default retry predicate
that the documentation recommends, and to decide whether a failure counts toward
the circuit breaker of a server. Failures that are not retryable prove that the
server answered, so they never open a circuit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from aiolimiter import AsyncLimiter
from purgatory import AsyncCircuitBreakerFactory
from tenacity import AsyncRetrying

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

    retry = AsyncRetrying(stop=stop_after_attempt(3), retry=retry_if_exception(is_retryable))
    ```

    Args:
        error: The exception to classify.

    Returns:
        `True` if the operation may be retried.
    """
    if not isinstance(error, Exception):
        return False
    return categorize_failure(error) not in _NOT_RETRYABLE


@dataclass(frozen=True, slots=True, kw_only=True)
class ResiliencePolicy:
    """How the operations on a server are protected.

    `MCPRuntime(resilience=...)` sets the policy of every server, and
    `register_server(..., resilience=...)` replaces it for one server. To change a
    single setting for one server, derive the policy from the runtime's:
    `dataclasses.replace(runtime.resilience, operation_timeout=5)`.

    The objects are the libraries' own: pass any `tenacity.AsyncRetrying`,
    `aiolimiter.AsyncLimiter`, or `purgatory.AsyncCircuitBreakerFactory`, including a
    factory whose unit of work keeps circuit state in Redis
    (`purgatory.AsyncRedisUnitOfWork`, with the `redis` extra) to share it between
    processes. Objects in a policy shared by several servers are shared too: one rate
    limit and one set of circuits for all of them.

    Attributes:
        operation_timeout: The timeout of each attempt, in seconds; none when `None`.
        retry: The retry policy; a single attempt when `None`. The runtime always
            re-raises the last error. Use `retry_if_exception(is_retryable)` as its
            predicate.
        retry_unsafe_tools: Whether tool calls are retried even when the tool is not
            idempotent. By default, only tools that declare `readOnlyHint` or
            `idempotentHint` are retried, because repeating any other tool call
            after a timeout or a lost connection can repeat its side effects.
        rate_limiter: A rate limit applied to every attempt; none when `None`.
        circuit_breaker: The circuit breakers, keyed by server and operation. When
            `None`, each server gets its own in-memory breakers (5 failures,
            30 seconds), which are discarded when the server is unregistered.
        max_concurrency: The maximum number of operations that run at the same time
            on one server, within the runtime-wide limit; unlimited when `None`.
    """

    operation_timeout: float | None = None
    retry: AsyncRetrying | None = None
    retry_unsafe_tools: bool = False
    rate_limiter: AsyncLimiter | None = None
    circuit_breaker: AsyncCircuitBreakerFactory | None = None
    max_concurrency: int | None = None

    def __post_init__(self) -> None:
        """Validate the policy.

        Raises:
            ConfigurationError: If a value is invalid.
        """
        timeout = self.operation_timeout
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            msg = f"operation_timeout must be a positive number of seconds, got {timeout!r}"
            raise ConfigurationError(msg)
        if self.retry is not None and not isinstance(self.retry, AsyncRetrying):
            msg = f"retry must be a tenacity.AsyncRetrying, got {type(self.retry).__name__}"
            raise ConfigurationError(msg)
        if not isinstance(self.retry_unsafe_tools, bool):
            msg = f"retry_unsafe_tools must be a bool, got {self.retry_unsafe_tools!r}"
            raise ConfigurationError(msg)
        if self.rate_limiter is not None and not isinstance(self.rate_limiter, AsyncLimiter):
            msg = (
                "rate_limiter must be an aiolimiter.AsyncLimiter, got "
                f"{type(self.rate_limiter).__name__}"
            )
            raise ConfigurationError(msg)
        if self.circuit_breaker is not None and not isinstance(
            self.circuit_breaker, AsyncCircuitBreakerFactory
        ):
            msg = (
                "circuit_breaker must be a purgatory.AsyncCircuitBreakerFactory, got "
                f"{type(self.circuit_breaker).__name__}"
            )
            raise ConfigurationError(msg)
        limit = self.max_concurrency
        if limit is not None and (
            isinstance(limit, bool) or not isinstance(limit, int) or limit < 1
        ):
            msg = f"max_concurrency must be a positive integer, got {limit!r}"
            raise ConfigurationError(msg)
