"""Framework integrations.

The core of `mcp_capability_router` depends on no agent framework. Each
integration lives in a submodule of its own and needs the matching extra:

- `mcp_capability_router.integrations.langchain`: LangChain tools, agent
  middleware, embeddings, and vector stores; `pip install
  "mcp-capability-router[langchain]"`.

Other frameworks use the core directly: `MCPRuntime.route_tools` returns
`RoutedTool` handles with the name, description, and JSON schema a model needs,
and `MCPRuntime.as_mcp_server` exposes the router to any MCP client.
"""
