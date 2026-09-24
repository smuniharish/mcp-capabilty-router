"""One agent, multiple real MCP servers registered into a single ``MCPRuntime``.

Every other real-MCP example in this directory (``real_filesystem_mcp.py``, ``real_git_mcp.py``,
``real_fetch_mcp.py``, ``real_everything_mcp.py``) deliberately registers exactly one MCP server,
to keep the smoke test focused. This example demonstrates the case those leave out: a single
runtime -- and a single ``create_agent`` agent built on top of it -- routing across *two
simultaneously connected* real MCP servers (the official Filesystem MCP server and the official
Git MCP server), both launched as real subprocesses over stdio.

This matters because the whole point of the router is to sit in front of however many MCP
servers an application connects, not just one: ``retrieve()`` and ``query()`` search across every
registered server's capabilities together (unless ``server_id`` narrows the search), and
``execute()`` dispatches to whichever server actually owns the selected capability. Nothing about
the runtime, the registry, or the retriever changes when a second server joins; only more
capabilities become available to route.

Prerequisites:
    Node.js with npm/npx on PATH (Filesystem MCP server).
    uv/uvx and Git on PATH (Git MCP server).
    uv sync --extra mcp --extra agents --extra openai --extra examples
    EXPLABS_API_KEY set in .env (see .env.example) for the real ``create_agent`` call.

Run:
    uv run python -m examples.real_multi_mcp_single_agent

Both servers are launched as temporary, credential-free processes against a scratch directory
and a freshly initialized empty Git repository; nothing outside those temporary paths is touched.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from mcp_capability_router import MCPRuntime

from .mcp_smoke_support import require_command, run_smoke


async def main() -> None:
    require_command("npx", "Install Node.js from https://nodejs.org/ and reopen the terminal.")
    require_command(
        "uvx", "Install uv from https://docs.astral.sh/uv/getting-started/installation/."
    )
    require_command(
        "git", "Install Git from https://git-scm.com/downloads and reopen the terminal."
    )

    try:
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise SystemExit(
            "Install optional agent dependencies first: "
            "uv sync --extra agents --extra openai --extra examples"
        ) from exc

    load_dotenv()
    api_key = os.environ.get("EXPLABS_API_KEY")
    if not api_key:
        raise SystemExit("Set EXPLABS_API_KEY in .env before running this example.")
    model = ChatOpenAI(
        model=os.environ.get("EXPLABS_MODEL", "gpt-5.6-luna"),
        base_url=os.environ.get("EXPLABS_BASE_URL", "https://api.experientiallabs.ai/v1"),
        api_key=api_key,
    )

    with tempfile.TemporaryDirectory() as fs_directory, tempfile.TemporaryDirectory() as repo_dir:
        fs_root = Path(fs_directory)
        (fs_root / "router-note.txt").write_text(
            "multi-server single-agent smoke test", encoding="utf-8"
        )
        repository = Path(repo_dir)
        await asyncio.to_thread(subprocess.run, ["git", "init", "-q", str(repository)], check=True)

        # One MultiServerMCPClient can host any number of named server configs; the router
        # bridges each one into its own registered server_id via register_mcp_client.
        client = MultiServerMCPClient(
            {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", str(fs_root)],
                    "transport": "stdio",
                },
                "git": {
                    "command": "uvx",
                    "args": [
                        "--system-certs",
                        "mcp-server-git",
                        "--repository",
                        str(repository),
                    ],
                    "transport": "stdio",
                },
            },
            handle_tool_errors=False,
        )

        async with MCPRuntime() as runtime:
            await runtime.register_mcp_client("filesystem", client)
            await runtime.register_mcp_client("git", client)
            # Both servers are discovered concurrently; the registry ends up with tools
            # from both, tagged by server_id.
            await runtime.refresh()

            all_tools = await runtime.retrieve("file or repository status", limit=50)
            servers_seen = sorted({tool.server_id for tool in all_tools})
            print("capabilities discovered across servers:", servers_seen)
            if servers_seen != ["filesystem", "git"]:
                raise RuntimeError(
                    f"Expected capabilities from both 'filesystem' and 'git', got {servers_seen}"
                )

            # Build one agent whose tool belt spans both real MCP servers at once.
            fs_tool_capability = next(t for t in all_tools if t.name == "read_text_file")
            git_tool_capability = next(t for t in all_tools if t.name == "git_status")

            async def read_note(**arguments):
                return await runtime.execute(fs_tool_capability.capability_id, arguments)

            async def repo_status(**arguments):
                return await runtime.execute(git_tool_capability.capability_id, arguments)

            tools = [
                StructuredTool.from_function(
                    coroutine=read_note,
                    name=fs_tool_capability.name,
                    description=fs_tool_capability.description or "Read a text file.",
                    args_schema=fs_tool_capability.schema,
                ),
                StructuredTool.from_function(
                    coroutine=repo_status,
                    name=git_tool_capability.name,
                    description=git_tool_capability.description or "Get git repository status.",
                    args_schema=git_tool_capability.schema,
                ),
            ]
            agent = create_agent(model=model, tools=tools)
            result = await agent.ainvoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                "Read router-note.txt, then also check the git repository "
                                f"status for {repository}. Summarize both results."
                            ),
                        }
                    ]
                }
            )
            print(result["messages"][-1].content)


if __name__ == "__main__":
    run_smoke(main())
