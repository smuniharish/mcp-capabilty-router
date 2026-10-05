"""Route tools, resources, and prompts through the same runtime.

All three kinds of MCP capability are indexed together, retrieved by type, and
used through their own operation.
"""

import asyncio

from common import billing_server

from mcp_capability_router import CapabilityType, MCPRuntime, Prompt, RefreshPolicy


async def main() -> None:
    async with MCPRuntime() as runtime:
        await runtime.register_mcp(
            "billing", billing_server(), refresh=RefreshPolicy(on_register=True)
        )
        for capability in await runtime.retrieve("", limit=10):
            print(f"{capability.type:<8} {capability.capability_id}")

        [tool] = await runtime.retrieve(
            "refund an invoice", type=CapabilityType.TOOL, limit=1
        )
        print(f"\ntool {tool.name} is destructive: {tool.metadata['annotations']}")
        message = await runtime.execute(
            tool.capability_id, {"invoice_id": "inv-1", "amount": 200}
        )
        print(f"refund: {message.artifact['structured_content']}")

        [policy] = await runtime.retrieve(
            "refund policy", type=CapabilityType.RESOURCE, limit=1
        )
        [contents] = await runtime.read_resource(policy.capability_id)
        print(f"\n{policy.name} ({contents.mime_type}):\n{contents.text}")

        [prompt] = await runtime.retrieve(
            "explain an invoice", type=CapabilityType.PROMPT, limit=1
        )
        assert isinstance(prompt, Prompt)
        print(f"\nprompt arguments: {[argument.name for argument in prompt.arguments]}")
        rendered = await runtime.get_prompt(
            prompt.capability_id, {"invoice_id": "inv-2"}
        )
        for message in rendered.messages:
            print(f"{message.role}: {message.content.text}")


if __name__ == "__main__":
    asyncio.run(main())
