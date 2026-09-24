"""Example D: LangChain-style Tools + Resources combined selection (no Prompts).

Run:
    uv run python -m examples.tools_and_resources

Credential-free: one adapter exposes Tools and Resources together, and the example
retrieves/selects/executes across both types in one workflow while leaving Prompts
untouched, demonstrating a two-type (not three-type) combination independently of
``combined_workflow.py``'s full Tool+Resource+Prompt example.
"""

from __future__ import annotations

import asyncio

from mcp_capability_router import CapabilityType, MCPRuntime


class InventoryAdapter:
    def __init__(self) -> None:
        self._catalog_doc = "SKU-100: wireless mouse, 42 in stock."

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": "check_stock", "description": "check stock level for a SKU"}]

    async def list_resources(self):
        return [
            {
                "uri": "file:///catalog.txt",
                "name": "catalog",
                "description": "product catalog reference",
            }
        ]

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        sku = (arguments or {}).get("sku", "SKU-100")
        return {"sku": sku, "in_stock": 42}

    async def read_resource(self, uri):
        return self._catalog_doc

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_server("inventory", lambda: InventoryAdapter())
        await runtime.refresh_server("inventory")

        assert await runtime.retrieve("anything", type=CapabilityType.PROMPT) == []

        tool = (await runtime.retrieve("stock", type=CapabilityType.TOOL))[0]
        resource = (await runtime.retrieve("catalog", type=CapabilityType.RESOURCE))[0]

        stock = await runtime.execute(tool.capability_id, {"sku": "SKU-100"})
        reference = await runtime.read_resource(resource.capability_id)

        print(f"{reference} Live stock check: {stock['in_stock']} units of {stock['sku']}.")


if __name__ == "__main__":
    asyncio.run(main())
