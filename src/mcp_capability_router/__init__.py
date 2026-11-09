"""Asyncio-first capability routing for MCP tools, resources, and prompts.

Every public name is importable from this package, except the OpenTelemetry
interceptor in `mcp_capability_router.otel`, which needs the `otel` extra, and the
conformance tests in `mcp_capability_router.testing`.
"""

import logging
from importlib.metadata import PackageNotFoundError, version

from .adapters import FastMCPAdapter, FastMCPTarget
from .agents import CapabilityRoutingMiddleware
from .contracts import (
    AdapterFactory,
    CallNext,
    CapabilityRegistry,
    CapabilityRetriever,
    Interceptor,
    InterceptorFunction,
    InterceptorLike,
    MCPAdapter,
    Operation,
    OperationContext,
)
from .errors import (
    AuthenticationError,
    AuthorizationError,
    CapabilityNotFoundError,
    CapabilityTypeError,
    CircuitOpenError,
    ConfigurationError,
    DiscoveryError,
    InvalidRequestError,
    MCPCapabilityRouterError,
    PromptRetrievalError,
    ProtocolError,
    RateLimitError,
    RefreshError,
    ResourceReadError,
    RuntimeClosedError,
    ServerConnectionError,
    ServerError,
    ServerNotFoundError,
    ServerUnavailableError,
    ToolExecutionError,
)
from .interceptors import InMemoryResultCacheStore, ResultCacheStore, ToolResultCache
from .models import (
    Capability,
    CapabilityType,
    HealthState,
    Prompt,
    PromptArgument,
    Resource,
    Tool,
    make_capability_id,
)
from .refresh import RefreshEventSource, RefreshPolicy
from .registry import InMemoryRegistry
from .resilience import (
    FailureCategory,
    ResiliencePolicy,
    categorize_failure,
    is_retryable,
)
from .retrieval import EmbeddingRetriever, HybridRetriever, KeywordRetriever
from .runtime import CapabilityFilter, MCPRuntime, StateStoreFactory

try:
    __version__ = version("mcp-capability-router")
except PackageNotFoundError:  # pragma: no cover - only without installed metadata
    __version__ = "0.0.0"

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "AdapterFactory",
    "AuthenticationError",
    "AuthorizationError",
    "CallNext",
    "Capability",
    "CapabilityFilter",
    "CapabilityNotFoundError",
    "CapabilityRegistry",
    "CapabilityRetriever",
    "CapabilityRoutingMiddleware",
    "CapabilityType",
    "CapabilityTypeError",
    "CircuitOpenError",
    "ConfigurationError",
    "DiscoveryError",
    "EmbeddingRetriever",
    "FailureCategory",
    "FastMCPAdapter",
    "FastMCPTarget",
    "HealthState",
    "HybridRetriever",
    "InMemoryRegistry",
    "InMemoryResultCacheStore",
    "Interceptor",
    "InterceptorFunction",
    "InterceptorLike",
    "InvalidRequestError",
    "KeywordRetriever",
    "MCPAdapter",
    "MCPCapabilityRouterError",
    "MCPRuntime",
    "Operation",
    "OperationContext",
    "Prompt",
    "PromptArgument",
    "PromptRetrievalError",
    "ProtocolError",
    "RateLimitError",
    "RefreshError",
    "RefreshEventSource",
    "RefreshPolicy",
    "ResiliencePolicy",
    "Resource",
    "ResourceReadError",
    "ResultCacheStore",
    "RuntimeClosedError",
    "ServerConnectionError",
    "ServerError",
    "ServerNotFoundError",
    "ServerUnavailableError",
    "StateStoreFactory",
    "Tool",
    "ToolExecutionError",
    "ToolResultCache",
    "__version__",
    "categorize_failure",
    "is_retryable",
    "make_capability_id",
]
