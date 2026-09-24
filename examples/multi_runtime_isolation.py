"""Example M: Multiple isolated MCPRuntime instances (per-tenant/per-request isolation).

Run:
    uv run python -m examples.multi_runtime_isolation

Credential-free: two ``MCPRuntime`` instances are created side by side, each with its
own registry, retriever, resilience pipeline, and registered servers. Demonstrates that
nothing is process-global: registering a server (or tripping a circuit breaker) in one
runtime has zero effect on the other, which is the isolation guarantee multi-tenant
applications rely on.
"""

from __future__ import annotations

import asyncio

from mcp_capability_router import MCPRuntime
from mcp_capability_router.errors import ServerError


class TenantAdapter:
    def __init__(self, tenant: str, fail: bool = False) -> None:
        self.tenant = tenant
        self.fail = fail

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_tools(self):
        return [{"name": f"{self.tenant}_lookup", "description": "tenant-scoped lookup"}]

    async def list_resources(self):
        return []

    async def list_prompts(self):
        return []

    async def call_tool(self, name, arguments=None):
        if self.fail:
            raise RuntimeError(f"{self.tenant} backend unavailable")
        return {"tenant": self.tenant}

    async def read_resource(self, uri):
        raise NotImplementedError

    async def get_prompt(self, name, arguments=None):
        raise NotImplementedError


async def main() -> None:
    # Two runtimes, one per tenant, run concurrently with no shared mutable state.
    async with MCPRuntime() as tenant_a_runtime, MCPRuntime() as tenant_b_runtime:
        await tenant_a_runtime.register_server("acme", lambda: TenantAdapter("acme", fail=True))
        await tenant_b_runtime.register_server("globex", lambda: TenantAdapter("globex"))
        await tenant_a_runtime.refresh_server("acme")
        await tenant_b_runtime.refresh_server("globex")

        acme_capability = (await tenant_a_runtime.retrieve("lookup"))[0]
        try:
            await tenant_a_runtime.execute(acme_capability.capability_id)
        except Exception as error:
            print("tenant A call failed as expected:", error)
        print("tenant A health after failure:", await tenant_a_runtime.health("acme"))

        # Tenant B's runtime is a completely separate instance: unaffected by tenant
        # A's failing server, and it does not even know "acme" exists.
        globex_capability = (await tenant_b_runtime.retrieve("lookup"))[0]
        result = await tenant_b_runtime.execute(globex_capability.capability_id)
        print("tenant B call succeeded:", result)
        print("tenant B health:", await tenant_b_runtime.health("globex"))

        try:
            await tenant_b_runtime.health("acme")
        except ServerError as error:
            print("tenant B has no knowledge of tenant A's server:", error)


if __name__ == "__main__":
    asyncio.run(main())
