"""The in-memory registry behaves like a dictionary keyed by capability ID."""

from __future__ import annotations

import asyncio

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from mcp_capability_router import Capability, CapabilityType, InMemoryRegistry
from tests.support import prompt, resource, tool

SERVERS = st.sampled_from(["a", "b", "c"])
NAMES = st.sampled_from(["x", "y", "z"])


@st.composite
def capabilities(draw: st.DrawFn) -> Capability:
    server = draw(SERVERS)
    name = draw(NAMES)
    kind = draw(st.sampled_from(list(CapabilityType)))
    description = draw(st.sampled_from(["one", "two"]))
    if kind is CapabilityType.TOOL:
        return tool(server, name, description)
    if kind is CapabilityType.RESOURCE:
        return resource(server, name, name, description=description)
    return prompt(server, name, description=description)


class RegistryMachine(RuleBasedStateMachine):
    @initialize()
    def start(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.registry = InMemoryRegistry()
        self.model: dict[str, Capability] = {}

    def run(self, coroutine: object) -> object:
        return self.loop.run_until_complete(coroutine)  # type: ignore[arg-type]

    @rule(items=st.lists(capabilities(), max_size=4))
    def upsert(self, items: list[Capability]) -> None:
        self.run(self.registry.upsert_many(items))
        for item in items:
            self.model.pop(item.capability_id, None)
            self.model[item.capability_id] = item

    @precondition(lambda self: bool(self.model))
    @rule(data=st.data())
    def remove_known(self, data: st.DataObject) -> None:
        capability_id = data.draw(st.sampled_from(sorted(self.model)))
        self.run(self.registry.remove(capability_id))
        del self.model[capability_id]

    @rule(server=SERVERS)
    def remove_server(self, server: str) -> None:
        self.run(self.registry.remove_server(server))
        self.model = {key: c for key, c in self.model.items() if c.server_id != server}

    @invariant()
    def matches_the_model(self) -> None:
        assert list(self.run(self.registry.list())) == list(self.model.values())  # type: ignore[call-overload]
        for server in ("a", "b", "c"):
            expected = [c for c in self.model.values() if c.server_id == server]
            assert list(self.run(self.registry.list(server_id=server))) == expected  # type: ignore[call-overload]
            for kind in CapabilityType:
                assert list(
                    self.run(self.registry.list(server_id=server, type=kind))  # type: ignore[call-overload]
                ) == [c for c in expected if c.type is kind]
        for key, value in self.model.items():
            assert self.run(self.registry.get(key)) is value

    def teardown(self) -> None:
        loop = getattr(self, "loop", None)
        if loop is not None:
            loop.close()


TestRegistryMachine = RegistryMachine.TestCase
TestRegistryMachine.settings = settings(stateful_step_count=30)
