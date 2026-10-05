# Troubleshooting

## Capabilities and routing

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `CapabilityNotFoundError: ... refresh its server first` | The server was never refreshed, or the ID is wrong. | Use `RefreshPolicy(on_register=True)` or `refresh_server`; IDs are `<server_id>:<type>:<name>`, and resource names are full URIs. |
| `retrieve` returns `[]` | Empty registry, or no shared words with the request. | Refresh first; use `query` with `on_query_miss`; improve tool descriptions; use `EmbeddingRetriever`. |
| The wrong tool ranks first | Keyword retrieval matches words, not meanings. | Improve names, descriptions, and tags; filter by `server_id` or `type`; raise `limit`; use embeddings. |
| `CapabilityTypeError` | A resource or prompt passed to `execute`, or similar. | Use `execute` for tools, `read_resource` for resources, `get_prompt` for prompts. |
| `InvalidRequestError` from `get_prompt` | A required argument is missing, or an argument is not a string. | Pass every required argument as a string. |

## Refresh

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `RefreshError` | Discovery failed. | Inspect `error.__cause__` and `error.result.errors`; the registry keeps its contents. |
| Registration raises `RefreshError` | `on_register` refresh failed; nothing was registered. | Fix the server or its credentials, then register again. |
| New tools never appear | No trigger refreshed the server. | Add `change_events`, `on_query_miss`, or `interval`. Notifications need an open session; `on_register` opens it. |
| Background refresh failures are invisible | They are logged, not raised. | Configure the `mcp_capability_router` logger at `WARNING`. |
| Every capability is rewritten after a restart | Expected: each registration's first refresh stores every capability. | Nothing to fix; later refreshes write only changes. |
| Capabilities of a server vanished from a shared registry | Another process unregistered the server, or changed its capabilities. | Let one process own each server; schedule `RefreshMode.FULL` refreshes to restore them. |

## Operations

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `CircuitOpenError` | Repeated retryable failures opened the circuit of that operation. | Check `health(server_id)` and the server; a trial call is admitted after the open period (30 s by default). |
| `TimeoutError` with a note | An attempt exceeded `operation_timeout`. | Raise the timeout for slow tools, or fix the server. |
| `ToolExecutionError` | The tool ran and reported an error, often invalid arguments. | Compare arguments with `tool.input_schema`; it is never retried. |
| `AuthenticationError`, `AuthorizationError` | Rejected credentials or a forbidden operation, or an interceptor's policy. | Fix credentials in the target or factory; not retried. |
| `ServerConnectionError` | The server is unreachable or the session was lost. | The next operation reconnects; check the URL, the command, and the network. |
| `ConfigurationError` | Invalid argument, duplicate server ID, an ID still being unregistered, or an object that does not implement its protocol. | Read the message; it names the problem. Await `unregister_server` before reusing an ID. |
| `ServerNotFoundError: server ... is closed` | An operation was still queued when its server was unregistered or its runtime closed. | Expected during shutdown; the closed server is not reconnected. |
| `RuntimeClosedError` | The runtime was used after `close`, or closed during a registration. | Keep one runtime open for the application's lifetime. |

## Agents

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| No routed tools are offered | Synchronous `invoke`, or no match for the latest user message. | Use `ainvoke` or `astream`; check `await runtime.retrieve(message, type=CapabilityType.TOOL)`. |
| `Tool name ... is ambiguous between servers` | Server IDs like `crm` and `crm_eu` make `<server_id>_<tool>` names ambiguous. | Use hyphens in server IDs, or scope the middleware with `server_id`. |
| A human-approval rule never triggers | The rule uses the MCP name, but routed names are prefixed. | Use `<server_id>_<tool>`, or scope the middleware to one server. |
| The agent run aborts on a tool error | An exception that is neither a router error nor a timeout, from a custom adapter. | Raise router exceptions from adapters. |
