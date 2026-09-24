"""Multiple agents, each bound to a *different* real MCP server, in one LangGraph swarm.

``real_multi_mcp_single_agent.py`` shows one agent routing across two simultaneously connected
real MCP servers. This example shows the complementary case the user asked for: several
*different agents*, each restricted to its own real MCP server, cooperating in a single
LangGraph network. Both servers are registered into one shared ``MCPRuntime`` (so discovery,
resilience, and refresh are coordinated centrally), but each agent's tool belt is built from a
``retrieve(..., server_id=...)`` call scoped to only its own server -- ``file_agent`` never sees
git tools and ``git_agent`` never sees filesystem tools, even though both live in the same
registry.

Real MCP servers used:
    * Official Filesystem MCP server (``@modelcontextprotocol/server-filesystem``) -> ``file_agent``
    * Official Git MCP server (``mcp-server-git``) -> ``git_agent``

The two agents are connected as sequential nodes in a real LangGraph ``StateGraph`` -- the
``file_agent`` node runs first and hands its findings to the ``git_agent`` node. Both nodes are
genuine ``create_agent`` agents driven by a real model (``ChatOpenAI`` against the
EXPLABS_API_KEY endpoint), each restricted to tools from its own MCP server; only the plain
text handoff between graph nodes is custom, not the agents or their tool calls.

Prerequisites:
    Node.js with npm/npx on PATH (Filesystem MCP server).
    uv/uvx and Git on PATH (Git MCP server).
    uv sync --extra mcp --extra agents --extra openai --extra examples
    EXPLABS_API_KEY set in .env (see .env.example).

Run:
    uv run python -m examples.real_multi_agent_multi_mcp
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import StructuredTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import END, START, StateGraph

from mcp_capability_router import Capability, MCPRuntime

from .mcp_smoke_support import require_command, run_smoke


@dataclass
class NetworkState:
    request: str
    file_report: str = ""
    git_report: str = ""


def _tool_for(runtime: MCPRuntime, capability: Capability) -> StructuredTool:
    async def call(**arguments):
        return await runtime.execute(capability.capability_id, arguments)

    return StructuredTool.from_function(
        coroutine=call,
        name=capability.name,
        description=capability.description or "Selected MCP capability",
        args_schema=capability.schema,
    )


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
            "multi-agent multi-server smoke test", encoding="utf-8"
        )
        repository = Path(repo_dir)
        await asyncio.to_thread(subprocess.run, ["git", "init", "-q", str(repository)], check=True)

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
            await runtime.refresh()

            # Each agent is scoped to exactly one real MCP server via server_id filtering,
            # even though both servers share one runtime/registry underneath.
            fs_capabilities = await runtime.retrieve("read file", server_id="filesystem", limit=5)
            git_capabilities = await runtime.retrieve("repository status", server_id="git", limit=5)
            fs_tool = next(t for t in fs_capabilities if t.name == "read_text_file")
            git_tool = next(t for t in git_capabilities if t.name == "git_status")

            file_agent = create_agent(
                model,
                tools=[_tool_for(runtime, fs_tool)],
                system_prompt=(
                    "You can only read files via the filesystem MCP server. Read the "
                    "requested file and summarize its contents in one sentence."
                ),
            )
            git_agent = create_agent(
                model,
                tools=[_tool_for(runtime, git_tool)],
                system_prompt=(
                    "You can only check git repository status via the git MCP server. "
                    f"Use repo_path={repository} when calling the tool, and summarize "
                    "the repository status in one sentence."
                ),
            )

            async def file_node(state: NetworkState) -> dict[str, str]:
                result = await file_agent.ainvoke(
                    {"messages": [{"role": "user", "content": state.request}]}
                )
                return {"file_report": result["messages"][-1].content}

            async def git_node(state: NetworkState) -> dict[str, str]:
                result = await git_agent.ainvoke(
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": "Report the current repository status.",
                            }
                        ]
                    }
                )
                return {"git_report": result["messages"][-1].content}

            graph = StateGraph(NetworkState)
            graph.add_node("file_agent", file_node)
            graph.add_node("git_agent", git_node)
            graph.add_edge(START, "file_agent")
            graph.add_edge("file_agent", "git_agent")
            graph.add_edge("git_agent", END)
            workflow = graph.compile()

            result = await workflow.ainvoke({"request": "Read router-note.txt and summarize it."})
            print("file_agent (filesystem MCP):", result["file_report"])
            print("git_agent (git MCP):", result["git_report"])


if __name__ == "__main__":
    run_smoke(main())
