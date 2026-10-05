"""Validation of server IDs and limits, and qualified tool names."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..errors import ConfigurationError

_SERVER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


def validate_server_id(server_id: object) -> str:
    """Return `server_id` if it is a valid server ID.

    A server ID has 1 to 64 characters, starts with a letter or digit, and contains
    only letters, digits, hyphens, and underscores. That keeps capability IDs
    unambiguous and lets the ID prefix tool names that a model sees.

    Raises:
        ConfigurationError: If the ID is invalid.
    """
    if not isinstance(server_id, str) or _SERVER_ID.fullmatch(server_id) is None:
        msg = (
            f"invalid server ID {server_id!r}: use 1 to 64 letters, digits, "
            "hyphens, or underscores, starting with a letter or digit"
        )
        raise ConfigurationError(msg)
    return server_id


def validate_limit(limit: object) -> int:
    """Return `limit` if it is a positive integer.

    Raises:
        ConfigurationError: If `limit` is not a positive integer.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        msg = f"limit must be a positive integer, got {limit!r}"
        raise ConfigurationError(msg)
    return limit


def qualified_tool_name(server_id: str, name: str) -> str:
    """Return the tool name shown to a model when tools of several servers mix."""
    return f"{server_id}_{name}"


def split_qualified_tool_name(
    qualified: str, server_ids: Iterable[str]
) -> list[tuple[str, str]]:
    """Return every `(server_id, name)` pair that `qualified` can stand for."""
    return [
        (server_id, qualified[len(server_id) + 1 :])
        for server_id in server_ids
        if qualified.startswith(f"{server_id}_") and len(qualified) > len(server_id) + 1
    ]
