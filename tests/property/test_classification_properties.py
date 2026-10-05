"""Properties of failure classification, error translation, naming, and discovery."""

from __future__ import annotations

import asyncio

import httpx2
import pytest
from hypothesis import given
from hypothesis import strategies as st
from mcp.shared.exceptions import MCPError

from mcp_capability_router import (
    DiscoveryError,
    FailureCategory,
    ServerError,
    categorize_failure,
    errors,
    is_retryable,
    make_capability_id,
)
from mcp_capability_router._internal.discovery import discover_capabilities
from mcp_capability_router._internal.naming import (
    qualified_tool_name,
    split_qualified_tool_name,
    validate_server_id,
)
from mcp_capability_router._internal.translation import translate_error
from tests.support import FakeAdapter, mcp_tool

ROUTER_ERRORS = [
    value
    for value in vars(errors).values()
    if isinstance(value, type)
    and issubclass(value, errors.MCPCapabilityRouterError)
    and value is not errors.RefreshError
]
NOT_RETRYABLE = {
    FailureCategory.AUTHENTICATION_FAILURE,
    FailureCategory.AUTHORIZATION_FAILURE,
    FailureCategory.CAPABILITY_NOT_FOUND,
    FailureCategory.INVALID_REQUEST,
    FailureCategory.PROTOCOL_FAILURE,
    FailureCategory.TOOL_EXECUTION_FAILURE,
}
EXCEPTIONS = st.sampled_from(
    [*ROUTER_ERRORS, ValueError, KeyError, ConnectionError, TimeoutError, OSError]
).map(lambda kind: kind("message"))
SERVER_IDS = st.from_regex(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", fullmatch=True)


@given(EXCEPTIONS)
def test_retryability_follows_the_category(error: Exception) -> None:
    category = categorize_failure(error)
    assert isinstance(category, FailureCategory)
    assert is_retryable(error) is (category not in NOT_RETRYABLE)


@given(st.sampled_from([asyncio.CancelledError, KeyboardInterrupt, SystemExit]))
def test_process_control_is_never_retryable(kind: type[BaseException]) -> None:
    assert is_retryable(kind()) is False


@given(st.integers(min_value=400, max_value=599))
def test_http_failures_always_translate(status: int) -> None:
    request = httpx2.Request("GET", "https://example.com/mcp")
    error = httpx2.HTTPStatusError(
        "failed", request=request, response=httpx2.Response(status, request=request)
    )
    assert isinstance(translate_error(error), ServerError | TimeoutError)


@given(st.integers(min_value=-33000, max_value=-32000))
def test_mcp_errors_always_translate(code: int) -> None:
    assert isinstance(
        translate_error(MCPError(code, "failed")), ServerError | TimeoutError
    )


@given(SERVER_IDS, st.text(min_size=1, max_size=40))
def test_qualified_names_round_trip(server_id: str, name: str) -> None:
    assert validate_server_id(server_id) == server_id
    qualified = qualified_tool_name(server_id, name)
    assert (server_id, name) in split_qualified_tool_name(qualified, [server_id])


@given(
    SERVER_IDS,
    st.lists(st.from_regex(r"[a-z][a-z0-9_]{0,15}", fullmatch=True), max_size=12),
)
def test_discovery_assigns_unique_ids_or_rejects_duplicates(
    server_id: str, names: list[str]
) -> None:
    adapter = FakeAdapter(tools=[mcp_tool(name) for name in names])
    if len(set(names)) < len(names):
        with pytest.raises(DiscoveryError):
            asyncio.run(discover_capabilities(adapter, server_id))
        return
    capabilities = asyncio.run(discover_capabilities(adapter, server_id))
    assert [capability.capability_id for capability in capabilities] == [
        make_capability_id(server_id, "tool", name)  # type: ignore[arg-type]
        for name in names
    ]
