"""LangChain test doubles, for the suites that test the `langchain` extra."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from pydantic import Field

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


class ScriptedChatModel(BaseChatModel):
    """A chat model that replies with scripted messages and records bound tools.

    Copies made by `bind_tools` share the script position and the call log.
    """

    responses: list[AIMessage]
    bound: list[str] = Field(default_factory=list)
    calls: list[list[str]] = Field(default_factory=list)
    position: dict[str, int] = Field(default_factory=lambda: {"next": 0})

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:  # type: ignore[override]
        names = [item.name if isinstance(item, BaseTool) else item["name"] for item in tools]
        return self.model_copy(update={"bound": names})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(self.bound))
        index = self.position["next"]
        self.position["next"] += 1
        return ChatResult(generations=[ChatGeneration(message=self.responses[index])])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop)


def tool_messages(result: Mapping[str, Any]) -> list[ToolMessage]:
    """Return the tool messages of an agent result."""
    return [message for message in result["messages"] if isinstance(message, ToolMessage)]
