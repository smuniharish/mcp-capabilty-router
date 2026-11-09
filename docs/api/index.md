# API reference

Every core name is importable from the `mcp_capability_router` package. Framework
integrations are importable from `mcp_capability_router.integrations.<framework>`,
tracing from `mcp_capability_router.otel`, and conformance suites from
`mcp_capability_router.testing`. Modules whose names start with an underscore are
internal and may change without notice.

```python
from mcp_capability_router import MCPRuntime, QdrantRetriever, RefreshPolicy
from mcp_capability_router.integrations.langchain import CapabilityRoutingMiddleware
```

| Page | Contents |
| --- | --- |
| [Runtime](runtime.md) | `MCPRuntime` and `RoutedTool` |
| [Capabilities](models.md) | `Capability`, `Tool`, `Resource`, `Prompt`, `PromptArgument`, `CapabilityType`, `HealthState`, and `make_capability_id` |
| [Refresh policies](refresh.md) | `RefreshPolicy` and `RefreshEventSource` |
| [Retrieval](retrieval.md) | `QdrantRetriever`, `Embedder`, `RetrievalMode`, and `Fusion` |
| [Registries](registry.md) | `InMemoryRegistry` |
| [FastMCP adapter](adapters.md) | `FastMCPAdapter` and `FastMCPTarget` |
| [Gateway](gateway.md) | `GatewayMode`, `RouterProvider`, and `RouterSearchTransform` |
| [Integrations](integrations.md) | `CapabilityRoutingMiddleware`, `to_langchain_tool`, `mcp_client_tools`, `LangChainEmbedder`, and `VectorStoreRetriever` |
| [Extension contracts](contracts.md) | `MCPAdapter`, `CapabilityRegistry`, `CapabilityRetriever`, `Interceptor`, `Operation`, and `OperationContext` |
| [Resilience](resilience.md) | `ResiliencePolicy`, `FailureCategory`, `categorize_failure`, and `is_retryable` |
| [Caching, tracing, and testing](extensions.md) | `ToolResultCache`, `ResultCacheStore`, `OpenTelemetryInterceptor`, and the conformance suites |
| [Exceptions](errors.md) | The exception hierarchy |

The package follows [semantic versioning](https://semver.org). The names listed in
this reference form the public API.