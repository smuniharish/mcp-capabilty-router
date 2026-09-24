"""Run the official Git MCP server through a direct client and the router.

Prerequisites:
    uv/uvx and Git on PATH.
    uv sync --extra mcp

Run:
    uv run python -m examples.real_git_mcp

This smoke test creates a temporary Git repository and invokes the non-mutating ``git_status``
tool. The official server package is installed by uvx when it is not already cached.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import MCPRuntime

from .mcp_smoke_support import require_command, run_smoke, select_tool


async def main() -> None:
    require_command(
        "uvx", "Install uv from https://docs.astral.sh/uv/getting-started/installation/."
    )
    require_command(
        "git", "Install Git from https://git-scm.com/downloads and reopen the terminal."
    )

    with tempfile.TemporaryDirectory() as directory:
        repository = Path(directory)
        await asyncio.to_thread(
            subprocess.run,
            ["git", "init", "-q", str(repository)],
            check=True,
        )
        client = MultiServerMCPClient(
            {
                "git": {
                    "command": "uvx",
                    "args": ["--system-certs", "mcp-server-git", "--repository", str(repository)],
                    "transport": "stdio",
                }
            },
            handle_tool_errors=False,
        )

        async with MCPRuntime() as runtime:
            await runtime.register_mcp_client("git", client)
            await runtime.refresh_server("git")
            tool = select_tool(
                await runtime.retrieve("git status", server_id="git"),
                "git_status",
            )
            print(await runtime.execute(tool.capability_id, {"repo_path": str(repository)}))


if __name__ == "__main__":
    run_smoke(main())
