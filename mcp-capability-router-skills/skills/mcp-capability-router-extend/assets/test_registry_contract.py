"""Run with pytest from this directory after adapting registry_template.py."""

from registry_template import TableRegistry

from mcp_capability_router.testing import CapabilityRegistryContract


class TestTableRegistry(CapabilityRegistryContract):
    async def make_registry(self) -> TableRegistry:
        return TableRegistry()
