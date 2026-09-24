"""Shared prerequisites and tool selection for real MCP smoke examples."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from collections.abc import Coroutine, Iterable
from typing import Any

from langchain_core.tools import ToolException


class SmokePrerequisiteError(RuntimeError):
    """Raised when a required local launcher is unavailable."""


def require_command(command: str, installation_hint: str) -> None:
    """Fail with an actionable message before a client attempts to launch a server."""
    if shutil.which(command) is None:
        raise SmokePrerequisiteError(f"'{command}' was not found on PATH. {installation_hint}")


def npx_launcher(*package_args: str) -> tuple[str, list[str]]:
    """Return the official npx launcher, including the Windows command-shell wrapper."""
    if os.name == "nt":
        return "cmd", ["/c", "npx", "-y", *package_args]
    return "npx", ["-y", *package_args]


def select_tool(capabilities: Iterable[Any], name: str) -> Any:
    """Select one expected tool after discovery, or identify an incompatible server release."""
    tool = next((item for item in capabilities if item.name == name), None)
    if tool is None:
        raise RuntimeError(
            f"Connected MCP server did not advertise the expected '{name}' tool. "
            "Check the installed server version and its startup output."
        )
    return tool


def run_smoke(main: Coroutine[Any, Any, None]) -> None:
    """Run a smoke test with concise prerequisite and MCP tool error reporting."""
    try:
        asyncio.run(main)
    except SmokePrerequisiteError as error:
        print(f"Prerequisite error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except ToolException as error:
        print(f"MCP tool error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
