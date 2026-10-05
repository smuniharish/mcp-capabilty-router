from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError

import pytest
from refresh_engine import RefreshRequest, RefreshResult, RefreshStatus

from mcp_capability_router import (
    AuthenticationError,
    AuthorizationError,
    CapabilityNotFoundError,
    CapabilityType,
    CapabilityTypeError,
    ConfigurationError,
    DiscoveryError,
    FailureCategory,
    InvalidRequestError,
    MCPCapabilityRouterError,
    Prompt,
    PromptArgument,
    PromptRetrievalError,
    ProtocolError,
    RateLimitError,
    RefreshError,
    Resource,
    ResourceReadError,
    RuntimeClosedError,
    ServerConnectionError,
    ServerError,
    ServerNotFoundError,
    ServerUnavailableError,
    Tool,
    ToolExecutionError,
    categorize_failure,
    is_retryable,
    make_capability_id,
)
from mcp_capability_router._internal.naming import (
    qualified_tool_name,
    split_qualified_tool_name,
    validate_limit,
    validate_server_id,
)


def failed_result() -> RefreshResult:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return RefreshResult(
        refresh_id="r1",
        request=RefreshRequest(),
        status=RefreshStatus.FAILED,
        started_at=now,
        completed_at=now,
        duration=0.0,
    )


class TestModels:
    def test_capability_ids_combine_server_type_and_name(self) -> None:
        assert make_capability_id("fs", CapabilityType.TOOL, "read") == "fs:tool:read"
        assert (
            make_capability_id("fs", CapabilityType.RESOURCE, "file:///a.txt")
            == "fs:resource:file:///a.txt"
        )
        assert make_capability_id("fs", "prompt", "plan") == "fs:prompt:plan"  # type: ignore[arg-type]

    def test_subclasses_set_their_type(self) -> None:
        tool = Tool(capability_id="s:tool:t", server_id="s", name="t")
        resource = Resource(
            capability_id="s:resource:u", server_id="s", name="u", uri="u"
        )
        prompt = Prompt(capability_id="s:prompt:p", server_id="s", name="p")
        assert (tool.type, resource.type, prompt.type) == (
            CapabilityType.TOOL,
            CapabilityType.RESOURCE,
            CapabilityType.PROMPT,
        )
        assert tool.input_schema == {"type": "object", "properties": {}}
        assert tool.output_schema is None
        assert resource.mime_type is None
        assert prompt.arguments == ()

    def test_records_are_immutable_and_hashable_despite_mappings(self) -> None:
        tool = Tool(
            capability_id="s:tool:t",
            server_id="s",
            name="t",
            metadata={"annotations": {"read_only_hint": True}},
            input_schema={"type": "object"},
        )
        assert {tool, tool} == {tool}
        with pytest.raises(FrozenInstanceError):
            tool.name = "other"  # type: ignore[misc]

    def test_prompt_arguments_describe_requirements(self) -> None:
        argument = PromptArgument(name="topic", description="What", required=True)
        prompt = Prompt(
            capability_id="s:prompt:p", server_id="s", name="p", arguments=(argument,)
        )
        assert prompt.arguments[0].required is True


class TestErrors:
    def test_hierarchy_mirrors_builtin_semantics(self) -> None:
        assert issubclass(ConfigurationError, ValueError)
        assert issubclass(ServerNotFoundError, LookupError)
        assert issubclass(CapabilityNotFoundError, LookupError)
        assert issubclass(CapabilityTypeError, TypeError)
        assert issubclass(RuntimeClosedError, RuntimeError)
        assert issubclass(DiscoveryError, ProtocolError)
        for error in (
            ServerConnectionError,
            AuthenticationError,
            AuthorizationError,
            ServerUnavailableError,
            RateLimitError,
            ProtocolError,
            InvalidRequestError,
            ToolExecutionError,
            ResourceReadError,
            PromptRetrievalError,
        ):
            assert issubclass(error, ServerError)
            assert issubclass(error, MCPCapabilityRouterError)

    def test_refresh_error_keeps_the_result(self) -> None:
        result = failed_result()
        error = RefreshError("failed", result)
        assert error.result is result
        assert str(error) == "failed"


class TestFailureClassification:
    @pytest.mark.parametrize(
        ("error", "category"),
        [
            (AuthenticationError(), FailureCategory.AUTHENTICATION_FAILURE),
            (AuthorizationError(), FailureCategory.AUTHORIZATION_FAILURE),
            (RateLimitError(), FailureCategory.RATE_LIMITED),
            (ServerUnavailableError(), FailureCategory.SERVER_UNAVAILABLE),
            (ProtocolError(), FailureCategory.PROTOCOL_FAILURE),
            (DiscoveryError(), FailureCategory.PROTOCOL_FAILURE),
            (InvalidRequestError(), FailureCategory.INVALID_REQUEST),
            (ConfigurationError(), FailureCategory.INVALID_REQUEST),
            (ServerNotFoundError(), FailureCategory.INVALID_REQUEST),
            (CapabilityTypeError(), FailureCategory.INVALID_REQUEST),
            (RuntimeClosedError(), FailureCategory.INVALID_REQUEST),
            (CapabilityNotFoundError(), FailureCategory.CAPABILITY_NOT_FOUND),
            (ToolExecutionError(), FailureCategory.TOOL_EXECUTION_FAILURE),
            (ResourceReadError(), FailureCategory.RESOURCE_READ_FAILURE),
            (PromptRetrievalError(), FailureCategory.PROMPT_RETRIEVAL_FAILURE),
            (ServerConnectionError(), FailureCategory.CONNECTION_FAILURE),
            (ConnectionResetError(), FailureCategory.CONNECTION_FAILURE),
            (TimeoutError(), FailureCategory.TIMEOUT),
            (ServerError(), FailureCategory.UNKNOWN),
            (ValueError(), FailureCategory.UNKNOWN),
        ],
    )
    def test_categories(self, error: Exception, category: FailureCategory) -> None:
        assert categorize_failure(error) is category

    def test_refresh_errors_are_categorized_by_their_cause(self) -> None:
        with_cause = RefreshError("failed", failed_result())
        with_cause.__cause__ = AuthenticationError()
        assert categorize_failure(with_cause) is FailureCategory.AUTHENTICATION_FAILURE
        assert categorize_failure(RefreshError("failed", failed_result())) is (
            FailureCategory.UNKNOWN
        )

    @pytest.mark.parametrize(
        "error",
        [
            AuthenticationError(),
            AuthorizationError(),
            InvalidRequestError(),
            ConfigurationError(),
            ServerNotFoundError(),
            RuntimeClosedError(),
            CapabilityNotFoundError(),
            ProtocolError(),
            ToolExecutionError(),
            asyncio.CancelledError(),
            KeyboardInterrupt(),
            SystemExit(),
        ],
    )
    def test_not_retryable(self, error: BaseException) -> None:
        assert is_retryable(error) is False

    @pytest.mark.parametrize(
        "error",
        [
            ServerConnectionError(),
            TimeoutError(),
            RateLimitError(),
            ServerUnavailableError(),
            ResourceReadError(),
            PromptRetrievalError(),
            ValueError(),
        ],
    )
    def test_retryable(self, error: Exception) -> None:
        assert is_retryable(error) is True


class TestNaming:
    @pytest.mark.parametrize("server_id", ["a", "fs", "Git-2", "x_y", "9" * 64])
    def test_valid_server_ids(self, server_id: str) -> None:
        assert validate_server_id(server_id) == server_id

    @pytest.mark.parametrize(
        "server_id", ["", "_x", "-x", "a:b", "a b", "a.b", "é", "9" * 65, 42, None]
    )
    def test_invalid_server_ids(self, server_id: object) -> None:
        with pytest.raises(ConfigurationError, match="invalid server ID"):
            validate_server_id(server_id)

    @pytest.mark.parametrize("limit", [1, 5, 10_000])
    def test_valid_limits(self, limit: int) -> None:
        assert validate_limit(limit) == limit

    @pytest.mark.parametrize("limit", [0, -1, True, 2.5, "3", None])
    def test_invalid_limits(self, limit: object) -> None:
        with pytest.raises(ConfigurationError, match="limit"):
            validate_limit(limit)

    def test_qualified_names_round_trip_and_report_ambiguity(self) -> None:
        assert qualified_tool_name("fs", "read_file") == "fs_read_file"
        assert split_qualified_tool_name("fs_read_file", ["fs", "git"]) == [
            ("fs", "read_file")
        ]
        assert split_qualified_tool_name("a_b_x", ["a", "a_b"]) == [
            ("a", "b_x"),
            ("a_b", "x"),
        ]
        assert split_qualified_tool_name("fs_", ["fs"]) == []
        assert split_qualified_tool_name("other", ["fs"]) == []
