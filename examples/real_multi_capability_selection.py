"""Select and use *multiple* tools and *multiple* resources in one workflow.

Every retrieval-focused example elsewhere in this directory narrows down to a single
capability (``matches[0]``) to keep the smoke test short. This example demonstrates the case
those leave out: ``retrieve()`` returning several capabilities of each type, and the workflow
genuinely using more than one of each -- multiple tools executed, multiple resources read --
against a real MCP server, not a hand-written adapter.

Real MCP server used: the official "Everything" MCP server
(``@modelcontextprotocol/server-everything``), which exists specifically to exercise a full
range of MCP capabilities for client/tooling tests. It advertises more than a dozen tools and
several static document resources, which is exactly the shape this example needs.

Prerequisites:
    Node.js with npm/npx on PATH.
    uv sync --extra mcp --extra examples

Run:
    uv run python -m examples.real_multi_capability_selection
"""

from __future__ import annotations

from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import CapabilityType, MCPRuntime

from .mcp_smoke_support import npx_launcher, require_command, run_smoke


async def main() -> None:
    require_command("npx", "Install Node.js from https://nodejs.org/ and reopen the terminal.")
    command, args = npx_launcher("@modelcontextprotocol/server-everything")
    client = MultiServerMCPClient(
        {"everything": {"command": command, "args": args, "transport": "stdio"}},
        handle_tool_errors=False,
    )

    async with MCPRuntime() as runtime:
        # discover_resources=True makes the router also index the server's Resources, not
        # just its Tools, so both types are selectable from the same registry.
        await runtime.register_mcp_client("everything", client, discover_resources=True)
        await runtime.refresh_server("everything")

        # --- Select and execute *multiple* tools ---------------------------------------
        tool_candidates = await runtime.retrieve(
            "sum of two numbers or echoes back input string",
            type=CapabilityType.TOOL,
            limit=5,
        )
        echo_tool = next(t for t in tool_candidates if t.name == "echo")
        sum_tool = next(t for t in tool_candidates if t.name == "get-sum")
        print(f"selected {len(tool_candidates)} candidate tools; using 2 of them:")

        echo_result = await runtime.execute(echo_tool.capability_id, {"message": "router says hi"})
        sum_result = await runtime.execute(sum_tool.capability_id, {"a": 19, "b": 23})
        print("  echo ->", echo_result)
        print("  get-sum ->", sum_result)

        # --- Select and read *multiple* resources ---------------------------------------
        resource_candidates = await runtime.retrieve(
            "document",
            type=CapabilityType.RESOURCE,
            limit=10,
        )
        if len(resource_candidates) < 2:
            raise RuntimeError(
                f"Expected multiple document resources, got {len(resource_candidates)}"
            )
        print(f"selected {len(resource_candidates)} candidate resources; reading 3 of them:")
        for resource in resource_candidates[:3]:
            content = await runtime.read_resource(resource.capability_id)
            preview = str(content)[:80].replace("\n", " ")
            print(f"  {resource.name}: {preview}...")


if __name__ == "__main__":
    run_smoke(main())
