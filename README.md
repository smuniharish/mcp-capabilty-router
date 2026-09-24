# mcp-capability-router

An async-first, runtime-isolated capability routing layer for LangChain, LangGraph, and
`langchain-mcp-adapters`. It discovers and routes MCP tools, resources, and prompts without
eagerly loading every capability into an agent context.

## Development

```powershell
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyrefly check
uv run mkdocs build
```

See the [documentation](docs/index.md) for architecture, integration, and examples.

