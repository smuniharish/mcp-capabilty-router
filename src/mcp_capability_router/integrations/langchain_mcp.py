from __future__ import annotations

from typing import Any, Protocol


class LangChainMCPClient(Protocol):
    """Client surface consumed by ``LangChainMCPAdapter``."""

    async def get_tools(self, *, server_name: str | None = None) -> list[Any]: ...

    async def get_resources(
        self,
        server_name: str | None = None,
        *,
        uris: str | list[str] | None = None,
    ) -> list[Any]: ...

    async def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        *,
        arguments: dict[str, Any] | None = None,
    ) -> Any: ...


class LangChainMCPAdapter:
    """Adapt one ``MultiServerMCPClient`` server to the runtime boundary.

    This is a generic bridge, not a Playwright or Filesystem client. The application still owns
    the adapter's server configuration, transport, authentication, and lifecycle policy.
    """

    def __init__(
        self,
        client: LangChainMCPClient,
        server_name: str,
        *,
        discover_resources: bool = False,
    ):
        self.client = client
        self.server_name = server_name
        self.discover_resources = discover_resources
        self.tools: dict[str, Any] = {}

    async def connect(self) -> None:
        self.tools = {
            tool.name: tool for tool in await self.client.get_tools(server_name=self.server_name)
        }

    async def close(self) -> None:
        self.tools.clear()

    async def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": getattr(tool, "description", ""),
                "schema": self._tool_schema(tool),
            }
            for name, tool in self.tools.items()
        ]

    @staticmethod
    def _tool_schema(tool: Any) -> dict[str, Any] | None:
        """Extract a JSON Schema for the tool's arguments, if the adapter exposes one."""
        schema = getattr(tool, "args_schema", None)
        if isinstance(schema, dict):
            return schema
        if hasattr(schema, "model_json_schema"):
            return schema.model_json_schema()
        return None

    async def list_resources(self) -> list[Any]:
        if not self.discover_resources:
            return []
        blobs = await self.client.get_resources(server_name=self.server_name)
        return [self._resource_entry(blob) for blob in blobs]

    @staticmethod
    def _resource_entry(blob: Any) -> dict[str, Any]:
        """Map a ``langchain_core.documents.Blob`` (what ``get_resources`` returns) to the
        plain ``{uri, name, description}`` shape ``discover_server`` expects. ``Blob`` carries
        the resource URI inside ``metadata['uri']``, not as a top-level attribute.
        """
        uri = str(getattr(blob, "metadata", {}).get("uri", ""))
        name = uri.rsplit("/", 1)[-1] or uri
        return {"uri": uri, "name": name, "description": getattr(blob, "mimetype", "") or ""}

    async def list_prompts(self) -> list[Any]:
        # The current adapter exposes prompt retrieval but not a prompt-list operation.
        return []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await self.tools[name].ainvoke(arguments or {})

    async def get_tool(self, name: str) -> Any:
        return self.tools[name]

    async def read_resource(self, uri: str) -> Any:
        blobs = await self.client.get_resources(server_name=self.server_name, uris=uri)
        if len(blobs) == 1:
            return blobs[0].as_string()
        return [blob.as_string() for blob in blobs]

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await self.client.get_prompt(
            self.server_name,
            name,
            arguments=arguments,
        )
