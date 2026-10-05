"""Register servers lazily and keep tenants isolated.

Registration connects to nothing; a server is contacted only when it is
refreshed or used. Each runtime owns its servers, registry, and circuit
breakers, so two tenants never see each other's capabilities.
"""

import asyncio

from common import billing_server, crm_server

from mcp_capability_router import MCPRuntime


async def main() -> None:
    async with MCPRuntime() as tenant_a, MCPRuntime() as tenant_b:
        await tenant_a.register_mcp("crm", crm_server())
        await tenant_b.register_mcp("billing", billing_server())
        print(f"tenant A servers: {tenant_a.servers}")
        print(f"capabilities before refresh: {len(await tenant_a.registry.list())}")

        await tenant_a.refresh_server("crm")
        await tenant_b.refresh_server("billing")
        print(f"capabilities after refresh: {len(await tenant_a.registry.list())}")

        for name, runtime in (("A", tenant_a), ("B", tenant_b)):
            matches = await runtime.retrieve("customer invoices refund", limit=10)
            print(f"tenant {name} sees: {[match.name for match in matches]}")


if __name__ == "__main__":
    asyncio.run(main())
