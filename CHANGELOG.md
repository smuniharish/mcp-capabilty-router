# Changelog

All notable changes are recorded here using
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0]

### Added

- Python 3.12 through 3.15 support, uv_build packaging, and Pyrefly type checking.
- ABC contracts for adapters, registries, retrievers, interceptors, and cache stores,
  with reusable async conformance suites in `mcp_capability_router.testing`.
- Refresh-engine 1.0 integration: policy-owned StateStores, per-server store factories,
  application-owned event publishers, async handlers and metrics, and fingerprints.
- FastMCP client options for authentication, sampling, elicitation, roots, and
  progress handlers, with support for application-owned clients.
- LangChain vector-store injection and weighted hybrid retrieval with reciprocal
  rank fusion.
- Runtime-wide and per-server `ResiliencePolicy`, per-server concurrency limits,
  safe-tool retry gating, and unhealthy-server exclusion with an explicit override.
- Read-only result caching with TTL, bounded LRU storage, single-flight requests,
  per-server invalidation, and a replaceable `ResultCacheStore`.
- OpenTelemetry MCP client spans and refresh-engine metrics through the `otel`
  extra; shared purgatory circuit state through the `redis` extra.
- SQLite and PostgreSQL durable registry and StateStore examples, Redis sharing,
  OTLP export, hybrid retrieval, and cache examples.
- Zensical documentation, current dependency groups, expanded CI, and two
  versioned Agent Skills with executable templates and evaluation cases.

## [0.2.0] - 2026-10-05

### Added

- FastMCP transports, LangChain agent middleware, refresh policies, ranked
  retrieval, classified failures, circuit health, metrics, and runnable examples.

## [0.1.0] - 2026-09-24

### Added

- Initial release.

[Unreleased]: https://github.com/smuniharish/mcp-capabilty-router/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/smuniharish/mcp-capabilty-router/releases/tag/v1.0.0
[0.2.0]: https://github.com/smuniharish/mcp-capabilty-router/releases/tag/v0.2.0
[0.1.0]: https://pypi.org/project/mcp-capability-router/0.1.0/
