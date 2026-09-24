from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from ..errors import (
    AuthenticationError,
    AuthorizationError,
    CapabilityNotFoundError,
    InvalidRequestError,
    PromptRetrievalError,
    ProtocolError,
    RateLimitError,
    ResourceReadError,
    ServerUnavailableError,
    ToolExecutionError,
)
from ..errors import (
    ConnectionError as MCPConnectionError,
)

Classifier = Callable[[BaseException], bool]


class FailureCategory(StrEnum):
    """Semantic failure categories used to drive retry/breaker/fallback/health decisions."""

    CONNECTION_FAILURE = "connection_failure"
    TIMEOUT = "timeout"
    AUTHENTICATION_FAILURE = "authentication_failure"
    AUTHORIZATION_FAILURE = "authorization_failure"
    RATE_LIMITED = "rate_limited"
    SERVER_UNAVAILABLE = "server_unavailable"
    PROTOCOL_FAILURE = "protocol_failure"
    INVALID_REQUEST = "invalid_request"
    CAPABILITY_NOT_FOUND = "capability_not_found"
    TOOL_EXECUTION_FAILURE = "tool_execution_failure"
    RESOURCE_READ_FAILURE = "resource_read_failure"
    PROMPT_RETRIEVAL_FAILURE = "prompt_retrieval_failure"
    UNKNOWN = "unknown"


# Categories that must never be blindly retried: they will not succeed on their own.
_NON_RETRYABLE_CATEGORIES = frozenset(
    {
        FailureCategory.AUTHENTICATION_FAILURE,
        FailureCategory.AUTHORIZATION_FAILURE,
        FailureCategory.INVALID_REQUEST,
        FailureCategory.CAPABILITY_NOT_FOUND,
        FailureCategory.PROTOCOL_FAILURE,
    }
)

_CATEGORY_BY_EXCEPTION: tuple[tuple[type[BaseException], FailureCategory], ...] = (
    (AuthenticationError, FailureCategory.AUTHENTICATION_FAILURE),
    (AuthorizationError, FailureCategory.AUTHORIZATION_FAILURE),
    (RateLimitError, FailureCategory.RATE_LIMITED),
    (ServerUnavailableError, FailureCategory.SERVER_UNAVAILABLE),
    (ProtocolError, FailureCategory.PROTOCOL_FAILURE),
    (InvalidRequestError, FailureCategory.INVALID_REQUEST),
    (CapabilityNotFoundError, FailureCategory.CAPABILITY_NOT_FOUND),
    (ToolExecutionError, FailureCategory.TOOL_EXECUTION_FAILURE),
    (ResourceReadError, FailureCategory.RESOURCE_READ_FAILURE),
    (PromptRetrievalError, FailureCategory.PROMPT_RETRIEVAL_FAILURE),
    (asyncio.TimeoutError, FailureCategory.TIMEOUT),
    (MCPConnectionError, FailureCategory.CONNECTION_FAILURE),
)


def categorize_failure(error: BaseException) -> FailureCategory:
    """Map an exception to a semantic :class:`FailureCategory`.

    Checked in declaration order so more specific subclasses (e.g. ``AuthenticationError``,
    a ``ServerError`` subclass) are matched before broader base classes.
    """
    for exception_type, category in _CATEGORY_BY_EXCEPTION:
        if isinstance(error, exception_type):
            return category
    return FailureCategory.UNKNOWN


@dataclass(frozen=True, slots=True)
class FailureClassification:
    retryable: bool
    reason: str
    category: FailureCategory = FailureCategory.UNKNOWN


class FailureClassifier:
    """Configurable, cancellation-safe classifier suitable for retry and breakers."""

    def __init__(
        self,
        *,
        retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
        non_retryable_exceptions: tuple[type[BaseException], ...] = (),
    ) -> None:
        self.retryable_exceptions = retryable_exceptions
        self.non_retryable_exceptions = (
            asyncio.CancelledError,
            KeyboardInterrupt,
            SystemExit,
            *non_retryable_exceptions,
        )

    def __call__(self, error: BaseException) -> bool:
        if isinstance(error, self.non_retryable_exceptions):
            return False
        return isinstance(error, self.retryable_exceptions)


def is_retryable_exception(
    error: BaseException,
    *,
    retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
    non_retryable_exceptions: tuple[type[BaseException], ...] = (
        asyncio.CancelledError,
        KeyboardInterrupt,
        SystemExit,
    ),
) -> bool:
    """Classify failures without ever retrying cancellation or process control errors."""
    if isinstance(error, non_retryable_exceptions):
        return False
    return isinstance(error, retryable_exceptions)


def classify_failure(
    error: BaseException, classifier: Classifier | None = None
) -> FailureClassification:
    category = categorize_failure(error)
    if classifier is not None:
        retryable = classifier(error)
    elif category is not FailureCategory.UNKNOWN:
        retryable = category not in _NON_RETRYABLE_CATEGORIES
    else:
        retryable = is_retryable_exception(error)
    return FailureClassification(retryable, "retryable" if retryable else "non-retryable", category)


def semantic_classifier(error: BaseException) -> bool:
    """Classifier callable driven by :func:`categorize_failure`.

    Non-retryable categories (auth, authorization, invalid request, capability-not-found,
    protocol failure) are never retried even though they are ordinary ``Exception``
    instances; everything else falls back to :func:`is_retryable_exception`.
    """
    if isinstance(error, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
        return False
    category = categorize_failure(error)
    if category in _NON_RETRYABLE_CATEGORIES:
        return False
    if category is not FailureCategory.UNKNOWN:
        return True
    return is_retryable_exception(error)
