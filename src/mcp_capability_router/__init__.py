"""Asyncio-first capability routing for MCP tools, resources, and prompts.

Every public name is importable from this package.
"""

from .adapters import FastMCPAdapter, FastMCPTarget
from .agents import CapabilityRoutingMiddleware
from .contracts import (
    CapabilityRegistry,
    CapabilityRetriever,
    Interceptor,
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
from .resilience import FailureCategory, categorize_failure, is_retryable
from .retrieval import EmbeddingRetriever, KeywordRetriever
from .runtime import MCPRuntime

__version__ = "0.2.0"

__all__ = [
    "AuthenticationError",
    "AuthorizationError",
    "Capability",
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
    "InMemoryRegistry",
    "Interceptor",
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
    "Resource",
    "ResourceReadError",
    "RuntimeClosedError",
    "ServerConnectionError",
    "ServerError",
    "ServerNotFoundError",
    "ServerUnavailableError",
    "Tool",
    "ToolExecutionError",
    "__version__",
    "categorize_failure",
    "is_retryable",
    "make_capability_id",
]
