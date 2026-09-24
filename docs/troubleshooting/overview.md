# Troubleshooting

* **No candidates:** call `refresh_server` after registration, check query terms, and remove an
  overly restrictive `type` or `server_id` filter. `query` can refresh named servers.
* **A capability disappeared:** refresh removes stale IDs returned by the server. Confirm the
  server's list response and capability names.
* **Connection occurs too early:** registration is lazy; `refresh_server`, `load`, and operations
  intentionally connect on demand.
* **`CapabilityNotFoundError`:** use the exact `capability_id` returned by retrieval and avoid
  retaining IDs after a refresh that removed them.
* **Wrong operation type:** `execute` accepts tools, `read_resource` accepts resources, and
  `get_prompt` accepts prompts.
* **External MCP integration fails:** test the adapter's transport, credentials, command, and
  server independently before passing it to the runtime. The router does not diagnose transport
  failures.
* **Documentation build fails:** use Python 3.12, run `uv sync --extra docs`, and then
  `uv run mkdocs build --strict` to see broken links or warnings.

## Useful diagnostics

```python
print(await runtime.health("server-id"))
print(await runtime.retrieve("", server_id="server-id", limit=100))
```
