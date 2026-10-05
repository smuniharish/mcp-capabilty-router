# Request lifecycle

This page follows a server, a request, and a refresh through the runtime.

## Registering a server

`register_server`, and `register_mcp` which calls it:

1. validates the server ID and the refresh policy, and reserves the ID;
2. stores the adapter factory, without calling it;
3. creates the server's refresh engine and circuit breakers;
4. if the policy sets `on_register`, refreshes the server, and undoes the
   registration if the refresh fails;
5. starts the interval scheduler and the change-event watcher that the policy asks
   for.

If the server is unregistered, or the runtime closes, before these steps complete,
the registration is undone and `register_server` raises. The ID stays reserved until
an unregistration completes, so it cannot be registered again in the meantime.

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
   query miss — asks the server's refresh engine for a refresh.
2. Discovery lists the server's tools, resources, and prompts through the resilience
   pipeline, as a `discover` operation. The first discovery of a registration also
   removes the server's capabilities that an earlier registration stored in the
   registry and the server no longer offers.
3. refresh-engine fingerprints every capability and compares it with the state of the
   last successful refresh, which each registration keeps in memory.
4. Added and modified capabilities are stored in the registry, and removed ones are
   deleted. After a failed discovery, nothing is deleted.
5. A manual refresh returns the result or raises `RefreshError`. A refresh triggered
   in the background logs its failure, and the next trigger tries again.

## Shutting down

`unregister_server` stops one server, and `close` stops all of them, concurrently.
Each first waits for a registration of the server that is still in progress, which
is then undone. For each server, the runtime:

1. stops the change-event watcher;
2. stops the interval scheduler;
3. closes the refresh engine, waiting for a running refresh;
4. closes the connection, after which operations that were still waiting fail
   instead of connecting again;
5. forgets its circuit breakers.

`unregister_server` also removes the server's capabilities from the registry. `close`
then closes the registry and leaves the capabilities of a durable registry in place.
If closing anything fails, or `close` is cancelled, every other resource is still
closed, and the errors are raised together as an exception group.
