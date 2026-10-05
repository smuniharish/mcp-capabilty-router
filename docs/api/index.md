# API reference

Every supported name is importable from the `mcp_capability_router` package. Modules
whose names start with an underscore are internal and may change without notice.

```python
from mcp_capability_router import CapabilityRoutingMiddleware, MCPRuntime, RefreshPolicy
```

| Page | Contents |
| --- | --- |
| [Runtime](runtime.md) | `MCPRuntime` |
| [Capabilities](models.md) | `Capability`, `Tool`, `Resource`, `Prompt`, `PromptArgument`, `CapabilityType`, `HealthState`, and `make_capability_id` |
| [Refresh policies](refresh.md) | `RefreshPolicy` and `RefreshEventSource` |
| [Retrieval](retrieval.md) | `KeywordRetriever` and `EmbeddingRetriever` |
| [Registries](registry.md) | `InMemoryRegistry` |
| [FastMCP adapter](adapters.md) | `FastMCPAdapter` and `FastMCPTarget` |
| [Agent middleware](agents.md) | `CapabilityRoutingMiddleware` |
| [Extension contracts](contracts.md) | `MCPAdapter`, `CapabilityRegistry`, `CapabilityRetriever`, `Interceptor`, `Operation`, and `OperationContext` |
| [Failure classification](resilience.md) | `FailureCategory`, `categorize_failure`, and `is_retryable` |
| [Exceptions](errors.md) | The exception hierarchy |

The package follows [semantic versioning](https://semver.org). The names listed in
this reference form the public API.
