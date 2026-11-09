"""Run the examples that need a model with scripted models instead.

The examples themselves run against real models when their environment variable
is set; these tests verify their wiring in every test run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.messages import AIMessage
from openai.types.chat import ChatCompletion

from tests.langchain_support import ScriptedChatModel

if TYPE_CHECKING:
    from types import ModuleType

    import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def load(name: str) -> ModuleType:
    if str(EXAMPLES) not in sys.path:
        sys.path.insert(0, str(EXAMPLES))
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), EXAMPLES / name)
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
                tool_calls=[call("billing_list_invoices", {"customer_id": "c-100"}, "1")],
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
                tool_calls=[call("billing_list_invoices", {"customer_id": "c-200"}, "2")],
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
                tool_calls=[call("issue_refund", {"invoice_id": "inv-1", "amount": 100}, "3")],
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


async def test_gateway_agent(capsys: pytest.CaptureFixture[str]) -> None:
    model = ScriptedChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[call("search_tools", {"query": "refund an invoice"}, "1")],
            ),
            AIMessage(
                content="",
                tool_calls=[
                    call(
                        "call_tool",
                        {
                            "name": "billing_issue_refund",
                            "arguments": {"invoice_id": "inv-1", "amount": 100},
                        },
                        "2",
                    )
                ],
            ),
            AIMessage(content="Refunded 100 of inv-1."),
        ]
    )
    await load("23_gateway_agent.py").main(model)
    assert capsys.readouterr().out.splitlines() == [
        "called search_tools: success",
        "called call_tool: success",
        "answer: Refunded 100 of inv-1.",
    ]


def completion(message: dict[str, Any]) -> ChatCompletion:
    return ChatCompletion.model_validate(
        {
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "created": 0,
            "model": "scripted",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls" if "tool_calls" in message else "stop",
                    "message": {"role": "assistant", **message},
                }
            ],
        }
    )


def function_call(call_id: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class ScriptedOpenAI:
    def __init__(self, responses: list[ChatCompletion]) -> None:
        self.responses = responses
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **request: Any) -> ChatCompletion:
        self.requests.append(request)
        return self.responses.pop(0)


async def test_any_framework(capsys: pytest.CaptureFixture[str]) -> None:
    client = ScriptedOpenAI(
        [
            completion(
                {
                    "content": None,
                    "tool_calls": [
                        function_call("1", "crm_search_customers", {"query": "globex"}),
                        function_call("2", "unknown_tool", {}),
                    ],
                }
            ),
            completion(
                {
                    "content": None,
                    "tool_calls": [
                        function_call("3", "billing_list_invoices", {"customer_id": "c-200"})
                    ],
                }
            ),
            completion({"content": "Globex has one open invoice, inv-2."}),
        ]
    )
    await load("22_any_framework.py").main(client, "scripted")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("routed tools: [")
    assert "crm_search_customers" in lines[0]
    assert "billing_list_invoices" in lines[0]
    assert lines[1:] == [
        "called crm_search_customers",
        "called unknown_tool",
        "called billing_list_invoices",
        "answer: Globex has one open invoice, inv-2.",
    ]
    tool_messages = [m for m in client.requests[-1]["messages"] if m["role"] == "tool"]
    assert "Globex" in tool_messages[0]["content"]
    assert tool_messages[1]["content"] == "error: no tool named 'unknown_tool'"
    assert "inv-2" in tool_messages[2]["content"]
