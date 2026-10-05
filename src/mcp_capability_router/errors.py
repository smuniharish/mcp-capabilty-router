"""Exceptions raised by mcp-capability-router.

Every exception derives from `MCPCapabilityRouterError`. Failures of an MCP server
operation derive from `ServerError`; the resilience pipeline classifies them with
`categorize_failure` to decide whether to retry them and whether they count toward
the circuit breaker of the server.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from refresh_engine import RefreshResult


class MCPCapabilityRouterError(Exception):
    """Base class of every exception raised by the router."""


class ConfigurationError(MCPCapabilityRouterError, ValueError):
    """An argument or a configuration value is invalid."""


class ServerNotFoundError(MCPCapabilityRouterError, LookupError):
    """No server is registered under the requested ID."""


class CapabilityNotFoundError(MCPCapabilityRouterError, LookupError):
    """The registry holds no capability with the requested ID."""


class CapabilityTypeError(MCPCapabilityRouterError, TypeError):
    """An operation was requested on a capability of another type."""


class RuntimeClosedError(MCPCapabilityRouterError, RuntimeError):
    """The runtime was used after it was closed."""


class RefreshError(MCPCapabilityRouterError):
    """A refresh failed as a whole.

    The exception is chained to the error that made discovery fail, when there is
    one.

    Attributes:
        result: The failed refresh result, including its issues.
    """

    def __init__(self, message: str, result: RefreshResult) -> None:
        """Create the error for a failed `result`."""
        super().__init__(message)
        self.result = result


class CircuitOpenError(MCPCapabilityRouterError):
    """The circuit breaker rejected an operation without calling the server."""


class ServerError(MCPCapabilityRouterError):
    """An operation on an MCP server failed."""


class ServerConnectionError(ServerError):
    """The server could not be reached, or the connection was lost."""


class AuthenticationError(ServerError):
    """The server rejected the credentials of the client."""


class AuthorizationError(ServerError):
    """The client is not allowed to perform the operation."""


class ServerUnavailableError(ServerError):
    """The server is temporarily unable to handle requests."""


class RateLimitError(ServerError):
    """The server throttled the client."""


class ProtocolError(ServerError):
    """The server violated the MCP protocol, or its protocol is incompatible."""


class DiscoveryError(ProtocolError):
    """The server returned an invalid capability listing."""


class InvalidRequestError(ServerError):
    """The server rejected the request as invalid."""


class ToolExecutionError(ServerError):
    """A tool reported an error while executing."""


class ResourceReadError(ServerError):
    """The server failed to read a resource."""


class PromptRetrievalError(ServerError):
    """The server failed to render a prompt."""
