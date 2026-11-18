# Request lifecycle

This page follows a server, a request, and a refresh through the runtime.

## Registering a server

`register_server`, and `register_mcp` which calls it, validates the server ID and
the refresh policy, and stores the adapter factory without calling it: no connection
is opened until an operation needs one. If the policy sets `on_register`, the server
is refreshed before `register_server` returns, and a failed refresh undoes the
registration. The interval schedule and change events that the policy asks for start
afterwards.

A registration that is interrupted by an unregistration or a shutdown is undone, and
`register_server` raises. A server ID cannot be registered again until its previous
server is fully closed.

## Routing a request

An agent turn with `CapabilityRoutingMiddleware` routes and calls tools like this:

![Agent routing](../assets/diagrams/agent-routing-light.png#only-light)
![Agent routing](../assets/diagrams/agent-routing-dark.png#only-dark)

1. Before the model call, the middleware queries the runtime with the latest user
   message.
2. The runtime lists the candidates from the registry, filtered by type and server,
   and the retriever ranks them. No server is called.
3. If nothing matches, the servers that allow it are refreshed, and the candidates are
   ranked again.
4. The model receives the best matching tools next to the agent's own tools.
5. When the model calls a routed tool, the middleware resolves its name to a
   capability and calls it through the runtime.
6. The result returns to the model as a tool message; a failure returns as an error
   tool message.

## Running an operation

Every operation on a server — `connect`, `discover`, `call_tool`, `read_resource`,
or `get_prompt` — runs through the resilience pipeline:

![Resilience pipeline](../assets/diagrams/resilience-pipeline-light.png#only-light)
![Resilience pipeline](../assets/diagrams/resilience-pipeline-dark.png#only-dark)

1. The operation waits for a slot of the concurrency limit.
2. The interceptors run, in order, around the rest of the pipeline.
3. The circuit breaker of the server and operation rejects the operation with
   `CircuitOpenError` if it is open.
4. The retry policy, if one is configured, decides whether a failed attempt is
   repeated; with `retry_if_exception(is_retryable)`, only failures that can pass are.
5. Each attempt waits for the rate limit, then runs under the timeout. On the first
   operation, the attempt creates the adapter and opens its connection.
6. The outcome is recorded in metrics and in the circuit breaker. A lost connection
   discards the adapter, so the next operation connects again.

## Refreshing a server

![Refresh flow](../assets/diagrams/refresh-flow-light.png#only-light)
![Refresh flow](../assets/diagrams/refresh-flow-dark.png#only-dark)

1. A trigger — a manual call, the registration, an interval, a change event, or a
   query miss — asks for a refresh of the server.
2. Discovery lists the server's tools, resources, and prompts through the resilience
   pipeline, as a `discover` operation.
3. refresh-engine compares them with the last successful refresh, and only added,
   modified, and removed capabilities are written to the registry. The first refresh
   of a registration also removes capabilities that an earlier registration stored
   and the server no longer offers. After a failed discovery, nothing is removed.
4. A manual refresh returns the result or raises `RefreshError`. A refresh triggered
   in the background logs its failure, and the next trigger tries again.

## Shutting down

`unregister_server` stops one server, and `close` stops all of them. Each waits for a
registration that is still in progress, which is then undone, and for a running
refresh. Background refreshes stop, the connection closes, and operations that were
still waiting fail instead of connecting again.

`unregister_server` also removes the server's capabilities from the registry. `close`
closes the registry and leaves the capabilities of a durable registry in place.
If closing anything fails, or `close` is cancelled, every other resource is still
closed, and the errors are raised together as an exception group.