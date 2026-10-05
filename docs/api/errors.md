# Exceptions

Every exception raised by the router derives from `MCPCapabilityRouterError`.
Failures of a server operation derive from `ServerError`. Timeouts raise the
built-in `TimeoutError`, with a note that names the operation and the server.

```text
MCPCapabilityRouterError
├── ConfigurationError (also a ValueError)
├── ServerNotFoundError (also a LookupError)
├── CapabilityNotFoundError (also a LookupError)
├── CapabilityTypeError (also a TypeError)
├── RuntimeClosedError (also a RuntimeError)
├── RefreshError
├── CircuitOpenError
└── ServerError
    ├── ServerConnectionError
    ├── AuthenticationError
    ├── AuthorizationError
    ├── ServerUnavailableError
    ├── RateLimitError
    ├── ProtocolError
    │   └── DiscoveryError
    ├── InvalidRequestError
    ├── ToolExecutionError
    ├── ResourceReadError
    └── PromptRetrievalError
```

::: mcp_capability_router.MCPCapabilityRouterError

::: mcp_capability_router.ConfigurationError

::: mcp_capability_router.ServerNotFoundError

::: mcp_capability_router.CapabilityNotFoundError

::: mcp_capability_router.CapabilityTypeError

::: mcp_capability_router.RuntimeClosedError

::: mcp_capability_router.RefreshError

::: mcp_capability_router.CircuitOpenError

::: mcp_capability_router.ServerError

::: mcp_capability_router.ServerConnectionError

::: mcp_capability_router.AuthenticationError

::: mcp_capability_router.AuthorizationError

::: mcp_capability_router.ServerUnavailableError

::: mcp_capability_router.RateLimitError

::: mcp_capability_router.ProtocolError

::: mcp_capability_router.DiscoveryError

::: mcp_capability_router.InvalidRequestError

::: mcp_capability_router.ToolExecutionError

::: mcp_capability_router.ResourceReadError

::: mcp_capability_router.PromptRetrievalError
