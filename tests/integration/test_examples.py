"""Run the examples that need a model with scripted models instead.

The examples themselves run against real models when their environment variable
is set; these tests verify their wiring in every test run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.messages import AIMessage

from tests.support import ScriptedChatModel

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def load(name: str) -> ModuleType:
    if str(EXAMPLES) not in sys.path:
        sys.path.insert(0, str(EXAMPLES))
    spec = importlib.util.spec_from_file_location(
        name.removesuffix(".py"), EXAMPLES / name
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def call(name: str, args: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


async def test_semantic_retrieval(capsys: pytest.CaptureFixture[str]) -> None:
    await load("08_semantic_retrieval.py").main(DeterministicFakeEmbedding(size=32))
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 3
    assert all(
        line.count(":tool:") + line.count(":resource:") + line.count(":prompt:") == 2
        for line in lines
    )


async def test_agent_middleware(capsys: pytest.CaptureFixture[str]) -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    call("billing_list_invoices", {"customer_id": "c-100"}, "1")
                ],
            ),
            AIMessage(content="Customer c-100 has one paid invoice, inv-1."),
        ]
    )
    await load("10_agent_middleware.py").main(model)
    assert capsys.readouterr().out.splitlines() == [
        "called billing_list_invoices: success",
        "answer: Customer c-100 has one paid invoice, inv-1.",
    ]
    assert "billing_list_invoices" in model.calls[0]


async def test_deep_agent(capsys: pytest.CaptureFixture[str]) -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[call("crm_search_customers", {"query": "globex"}, "1")],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    call("billing_list_invoices", {"customer_id": "c-200"}, "2")
                ],
            ),
            AIMessage(content="Globex has one open invoice, inv-2."),
        ]
    )
    await load("11_deep_agent.py").main(model)
    assert capsys.readouterr().out.splitlines() == [
        "routed tools called: ['crm_search_customers', 'billing_list_invoices']",
        "answer: Globex has one open invoice, inv-2.",
    ]


async def test_agent_swarm(capsys: pytest.CaptureFixture[str]) -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[call("search_customers", {"query": "acme"}, "1")],
            ),
            AIMessage(content="", tool_calls=[call("transfer_to_billing", {}, "2")]),
            AIMessage(
                content="",
                tool_calls=[
                    call("issue_refund", {"invoice_id": "inv-1", "amount": 100}, "3")
                ],
            ),
            AIMessage(content="Refunded 100 of inv-1 for Acme Corp."),
        ]
    )
    await load("12_agent_swarm.py").main(model)
    assert capsys.readouterr().out.splitlines() == [
        "called search_customers: success",
        "called transfer_to_billing: success",
        "called issue_refund: success",
        "answer: Refunded 100 of inv-1 for Acme Corp.",
    ]
