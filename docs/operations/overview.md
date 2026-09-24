# Operations overview

## Lifecycle

Create one `MCPRuntime` per application isolation boundary, register servers lazily, and
close it during application shutdown. Registration does not start a subprocess or open an
MCP session; `connect`, `refresh_server`, and capability execution are the points at which
the adapter is loaded.

## Operating model

Operate a runtime as an application-owned async resource. Set limits deliberately, monitor
server health, and keep application credentials and transport configuration at the adapter
boundary. See [concurrency](concurrency.md), [isolation and security](isolation.md),
[refresh](refresh.md), and [resilience](resilience.md) for the operating contracts.

## Deployment checklist

- Pin `uv.lock` in reproducible builds.
- Grant each MCP server only the filesystem, network, and subprocess permissions it needs.
- Set explicit operation timeouts and bounded retries.
- Keep runtime instances isolated between tenants or trust boundaries.
- Verify external MCP launchers and browser binaries during deployment, not at import time.
