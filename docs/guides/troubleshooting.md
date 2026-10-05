# Troubleshooting

## Capabilities

**`CapabilityNotFoundError: no capability '...'; refresh its server first`**
: The registry does not hold the capability. Refresh its server with
  `refresh_server`, or register it with `RefreshPolicy(on_register=True)`. Check the
  ID: it has the form `<server_id>:<type>:<name>`, and the name of a resource is its
  full URI.

**`CapabilityTypeError`**
: The ID belongs to another type of capability, for example a resource passed to
  `execute`. Use `execute` for tools, `read_resource` for resources, and `get_prompt`
  for prompts.

**`retrieve` returns nothing**
: Either the server was never refreshed, or no capability contains the words of the
  request. Use `query` with `on_query_miss`, check that the server's tool names and
  descriptions contain the words users use, or switch to `EmbeddingRetriever`.

**The wrong tool ranks first**
: Keyword retrieval matches words, not meanings. Improve the tool names, descriptions,
  and tags, raise `limit` so that the model can choose, or use
  `EmbeddingRetriever`. See [Retrieval](retrieval.md).

## Refresh

**`RefreshError: refresh of server '...' failed`**
: Discovery failed. The exception is chained to the cause, and `error.result.errors`
  lists the issues. The registry keeps its previous contents.

**New tools are not discovered**
: Nothing refreshed the server. Add `change_events`, `on_query_miss`, or an
  `interval` to its refresh policy. Change notifications arrive only while the
  connection is open; `on_register` opens it at registration.

**Background refreshes fail silently**
: Refreshes triggered by query misses, intervals, and change events log their failures
  as warnings on the `mcp_capability_router` logger instead of raising. Configure
  logging to see them.

## Operations

**`CircuitOpenError`**
: The server failed repeatedly, and its circuit for that operation is open. Check
  `health(server_id)` and the server itself. The circuit admits a trial call after the
  open period, 30 seconds by default.

**`TimeoutError`**
: An attempt exceeded `operation_timeout`. The exception note names the operation and
  the server. Raise the timeout for slow tools, or investigate the server.

**`ToolExecutionError`**
: The tool ran and reported an error, often because of invalid arguments. It is not
  retried. Compare the arguments with the tool's `input_schema`.

**`AuthenticationError` or `AuthorizationError`**
: The server rejected the credentials, or does not allow the operation. Check the
  credentials passed through the target. These errors are not retried and do not open
  circuits.

**`ConfigurationError: server '...' is already registered`**
: Server IDs are unique within a runtime. Unregister the server first, or choose
  another ID. The message says *being unregistered* while an unregistration of the
  ID is still in progress; await `unregister_server` before registering it again.

**`ServerNotFoundError: server '...' is closed`**
: An operation was still waiting, for example for a concurrency slot, when its server
  was unregistered or its runtime closed. The runtime does not reconnect a closed
  server.

**`RuntimeClosedError`**
: The runtime was used after `close`, or closed while a registration was in progress.
  Keep the runtime open for the lifetime of the application.

## Agents

**The agent never calls a routed tool**
: Invoke the agent with `ainvoke` or `astream`; the middleware is asynchronous. Check
  that the latest user message describes the task, and that `retrieve` finds the tool
  for that message.

**`Tool name '...' is ambiguous between servers`**
: Routed tools are named `<server_id>_<tool>`. When one server ID followed by an
  underscore starts another, such as `crm` and `crm_eu`, a name can match tools of
  both. Use hyphens in server IDs, such as `crm-eu`, or scope the middleware with
  `server_id`.

## Servers

**A stdio server does not start**
: The command must be on the `PATH` of the process, such as `npx` for Node.js
  servers or `uvx` for Python servers. Start the server by hand with the same command
  to see its errors.

**Errors are hard to read in logs**
: FastMCP logs through the `fastmcp` logger. Set its level to see protocol details, or
  to silence expected rejections in tests.
