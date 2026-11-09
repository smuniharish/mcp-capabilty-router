"""Framework-agnostic, asyncio-first capability routing for MCP tools, resources, and prompts.

Every public name of the core is importable from this package. The OpenTelemetry
interceptor lives in `mcp_capability_router.otel` (the `otel` extra), framework
integrations in `mcp_capability_router.integrations` (for example the `langchain`
extra), and the conformance tests in `mcp_capability_router.testing`.
"""

import logging
from importlib.metadata import PackageNotFoundError, version

from .adapters import FastMCPAdapter, FastMCPTarget
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
from .gateway import GatewayMode, RouterProvider, RouterSearchTransform
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
from .retrieval import Embedder, Fusion, QdrantRetriever, RetrievalMode, document_text
from .runtime import CapabilityFilter, MCPRuntime, StateStoreFactory
from .tools import RoutedTool

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
    "CapabilityType",
    "CapabilityTypeError",
    "CircuitOpenError",
    "ConfigurationError",
    "DiscoveryError",
    "Embedder",
    "FailureCategory",
    "FastMCPAdapter",
    "FastMCPTarget",
    "Fusion",
    "GatewayMode",
    "HealthState",
    "InMemoryRegistry",
    "InMemoryResultCacheStore",
    "Interceptor",
    "InterceptorFunction",
    "InterceptorLike",
    "InvalidRequestError",
    "MCPAdapter",
    "MCPCapabilityRouterError",
    "MCPRuntime",
    "Operation",
    "OperationContext",
    "Prompt",
    "PromptArgument",
    "PromptRetrievalError",
    "ProtocolError",
    "QdrantRetriever",
    "RateLimitError",
    "RefreshError",
    "RefreshEventSource",
    "RefreshPolicy",
    "ResiliencePolicy",
    "Resource",
    "ResourceReadError",
    "ResultCacheStore",
    "RetrievalMode",
    "RoutedTool",
    "RouterProvider",
    "RouterSearchTransform",
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
    "document_text",
    "is_retryable",
    "make_capability_id",
]
