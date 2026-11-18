# Request lifecycle

This page follows a server, a request, and a refresh through the runtime.

## Registering a server

`register_server` and `register_mcp` validate the server ID and refresh policy.
Connections are opened on demand, unless `on_register` requests a refresh before
registration returns. A failed initial refresh undoes the registration. Configured
interval and change-event refreshes run in the background.

A registration that is interrupted by an unregistration or a shutdown is undone, and
`register_server` raises. A server ID cannot be registered again until its previous
server is fully closed.

## Routing a request

An agent turn with `CapabilityRoutingMiddleware` routes and calls tools like this:

![Agent routing](../assets/diagrams/agent-routing-light.png#only-light)
![Agent routing](../assets/diagrams/agent-routing-dark.png#only-dark)

Before a model call, the middleware routes the latest user message and supplies
matching tools alongside the agent's own tools. Retrieval uses capability metadata;
on a miss, the runtime may refresh servers according to their policies. Routed tool
calls run through the runtime. Results and failures reach the model as tool messages.

## Running an operation

Every operation on a server — `connect`, `discover`, `call_tool`, `read_resource`,
or `get_prompt` — runs through the resilience pipeline:

![Resilience pipeline](../assets/diagrams/resilience-pipeline-light.png#only-light)
![Resilience pipeline](../assets/diagrams/resilience-pipeline-dark.png#only-dark)

Operations honor the configured concurrency and rate limits, interceptors, circuit
breakers, retries, and timeout. An open circuit rejects a call with
`CircuitOpenError`. Interceptors run once per operation, and the timeout applies to
each attempt. Configure retries with `retry_if_exception(is_retryable)` so failures
that cannot pass on another attempt are not repeated. Metrics record outcomes; after
a lost connection, the next operation reconnects.

## Refreshing a server

![Refresh flow](../assets/diagrams/refresh-flow-light.png#only-light)
![Refresh flow](../assets/diagrams/refresh-flow-dark.png#only-dark)

Manual calls and configured registration, interval, change-event, or query-miss
triggers refresh a server's tools, resources, and prompts. Successful discovery
updates the registry, including removal of capabilities the server no longer offers;
failed discovery removes nothing. A manual refresh returns its result or raises
`RefreshError`; a background failure is logged and a later trigger can retry.

## Shutting down

`unregister_server` stops one server, and `close` stops all of them. Each waits for a
registration that is still in progress, which is then undone, and for a running
refresh. Background refreshes stop, the connection closes, and operations that were
still waiting fail instead of connecting again.

`unregister_server` also removes the server's capabilities from the registry. `close`
closes the registry and leaves the capabilities of a durable registry in place.
If closing anything fails, or `close` is cancelled, every other resource is still
closed, and the errors are raised together as an exception group.