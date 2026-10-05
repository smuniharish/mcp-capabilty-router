"""Run the numbered examples and compare their output with the expected output.

Each example must exit successfully, write nothing to standard error, and print
exactly the text stored in `examples/output/<example>.txt`. Examples that need an
external service, a model, or Node.js are skipped unless the corresponding
environment variable is set; when they run, only their exit status is checked,
because their output depends on the model or on the server version.

Usage:
    python scripts/run_examples.py            # verify every example
    python scripts/run_examples.py --update   # rewrite the expected output
"""

from __future__ import annotations

import argparse
import difflib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
OUTPUT = EXAMPLES / "output"
REQUIRES = {
    "08_semantic_retrieval.py": "MCP_ROUTER_EXAMPLE_EMBEDDINGS",
    "10_agent_middleware.py": "MCP_ROUTER_EXAMPLE_MODEL",
    "11_deep_agent.py": "MCP_ROUTER_EXAMPLE_MODEL",
    "12_agent_swarm.py": "MCP_ROUTER_EXAMPLE_MODEL",
    "13_postgres_registry.py": "MCP_ROUTER_EXAMPLE_POSTGRES_DSN",
    "14_stdio_servers.py": "MCP_ROUTER_EXAMPLE_NODE",
}
VARIABLE_OUTPUT = {
    "08_semantic_retrieval.py",
    "10_agent_middleware.py",
    "11_deep_agent.py",
    "12_agent_swarm.py",
    "14_stdio_servers.py",
}
# langsmith, a LangChain dependency, calls asyncio.iscoroutinefunction, which Python
# 3.14 deprecates; every other warning is an error.
WARNING_OPTIONS = (
    "-W",
    "error",
    "-W",
    "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning",
)


def run(example: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *WARNING_OPTIONS, example.name],
        cwd=EXAMPLES,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        check=False,
    )


def check(example: Path, update: bool) -> bool:
    completed = run(example)
    stdout = completed.stdout.replace("\r\n", "\n")
    if example.name in VARIABLE_OUTPUT:
        if completed.returncode != 0:
            print(f"FAIL  {example.name} (exit code {completed.returncode})")
            print(completed.stderr)
            return False
        print(f"ok    {example.name} (output not compared)")
        return True
    if completed.returncode != 0 or completed.stderr:
        print(f"FAIL  {example.name} (exit code {completed.returncode})")
        print(completed.stderr)
        return False
    expected_path = OUTPUT / f"{example.stem}.txt"
    if update:
        expected_path.write_text(stdout, encoding="utf-8", newline="\n")
        print(f"wrote {expected_path.relative_to(ROOT).as_posix()}")
        return True
    expected = (
        expected_path.read_text(encoding="utf-8") if expected_path.exists() else ""
    )
    if stdout == expected:
        print(f"ok    {example.name}")
        return True
    print(f"FAIL  {example.name} printed unexpected output:")
    sys.stdout.writelines(
        difflib.unified_diff(
            expected.splitlines(keepends=True),
            stdout.splitlines(keepends=True),
            "expected",
            "actual",
        )
    )
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and verify the examples.")
    parser.add_argument(
        "--update", action="store_true", help="rewrite the expected output files"
    )
    arguments = parser.parse_args()
    failures = 0
    for example in sorted(EXAMPLES.glob("[0-9][0-9]_*.py")):
        variable = REQUIRES.get(example.name)
        if variable is not None and not os.environ.get(variable):
            print(f"skip  {example.name} (set {variable} to run it)")
            continue
        if not check(example, arguments.update):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
