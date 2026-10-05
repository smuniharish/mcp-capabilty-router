"""Validate the built distributions and smoke-test the wheel in clean environments.

Usage:
    python scripts/validate_distribution.py dist --python 3.12 --python 3.14
"""

from __future__ import annotations

import argparse
import email
import email.message
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DEPENDENCIES = {
    "aiolimiter",
    "anyio",
    "fastmcp",
    "httpx2",
    "langchain",
    "langchain-core",
    "mcp",
    "numpy",
    "purgatory",
    "refresh-engine",
    "tenacity",
}
DEVELOPMENT_PREFIXES = ("tests/", "examples/", "scripts/", "docs/", "benchmarks/")
# langsmith, a LangChain dependency, calls asyncio.iscoroutinefunction, which Python
# 3.14 deprecates; every other warning is an error.
WARNING_OPTIONS = (
    "-W",
    "error",
    "-W",
    "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning",
)

SMOKE_TEST = """
import asyncio
import sys

from fastmcp import FastMCP

import mcp_capability_router
from mcp_capability_router import MCPRuntime, RefreshPolicy

server = FastMCP("smoke")


@server.tool(description="Echo the text back.")
def echo(text: str) -> str:
    return text


async def main() -> None:
    async with MCPRuntime(operation_timeout=60) as runtime:
        await runtime.register_mcp(
            "smoke", server, refresh=RefreshPolicy(on_register=True)
        )
        [tool] = await runtime.retrieve("echo the text", limit=1)
        message = await runtime.execute(tool.capability_id, {"text": "ok"})
    assert tool.capability_id == "smoke:tool:echo", tool
    assert message.text == "ok", message


asyncio.run(main())
version = mcp_capability_router.__version__
assert version == sys.argv[1], version
print("smoke test passed on Python", sys.version.split()[0])
"""


def fail(message: str) -> NoReturn:
    raise SystemExit(f"distribution validation failed: {message}")


def project_version() -> str:
    source = (ROOT / "src" / "mcp_capability_router" / "__init__.py").read_text("utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', source, re.MULTILINE)
    if match is None:
        fail("cannot find __version__ in src/mcp_capability_router/__init__.py")
    return match.group(1)


def requirement_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9._-]+", requirement)
    if match is None:
        fail(f"unparsable requirement: {requirement!r}")
    return match.group(0).lower().replace("_", "-")


def validate_wheel(wheel: Path, version: str, requires_python: str) -> None:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata_files = [
            name for name in names if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            fail("the wheel must contain exactly one METADATA file")
        metadata = email.message_from_bytes(archive.read(metadata_files[0]))
    if "mcp_capability_router/py.typed" not in names:
        fail("the wheel does not contain the py.typed marker")
    if any(name.startswith(DEVELOPMENT_PREFIXES) for name in names):
        fail("the wheel contains development-only files")
    if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
        fail("the wheel does not contain the license file")
    validate_metadata(metadata, version, requires_python)


def specifiers(value: str | None) -> set[str]:
    return {item.strip() for item in (value or "").split(",") if item.strip()}


def validate_metadata(
    metadata: email.message.Message, version: str, requires_python: str
) -> None:
    expected = {
        "Name": "mcp-capability-router",
        "Version": version,
        "License-Expression": "Apache-2.0",
        "Description-Content-Type": "text/markdown",
    }
    for field, value in expected.items():
        if metadata[field] != value:
            fail(f"{field} is {metadata[field]!r}, expected {value!r}")
    if specifiers(metadata["Requires-Python"]) != specifiers(requires_python):
        fail(f"Requires-Python is {metadata['Requires-Python']!r}")
    dependencies = {
        requirement_name(requirement)
        for requirement in metadata.get_all("Requires-Dist", [])
        if "extra ==" not in requirement
    }
    if dependencies != RUNTIME_DEPENDENCIES:
        fail(f"runtime dependencies are {sorted(dependencies)}")
    urls = {url.split(",", 1)[0] for url in metadata.get_all("Project-URL", [])}
    if not {"Homepage", "Documentation", "Repository", "Issues", "Changelog"} <= urls:
        fail(f"project URLs are incomplete: {sorted(urls)}")
    if "Typing :: Typed" not in metadata.get_all("Classifier", []):
        fail("the Typing :: Typed classifier is missing")


def validate_sdist(sdist: Path) -> None:
    with tarfile.open(sdist, "r:gz") as archive:
        names = [name.split("/", 1)[1] for name in archive.getnames() if "/" in name]
    required = {
        "LICENSE",
        "README.md",
        "CHANGELOG.md",
        "pyproject.toml",
        "src/mcp_capability_router/__init__.py",
        "src/mcp_capability_router/py.typed",
        "tests/conftest.py",
    }
    missing = required - set(names)
    if missing:
        fail(f"the sdist is missing {sorted(missing)}")
    unexpected = [
        name
        for name in names
        if name.startswith(
            (
                ".github/",
                "benchmarks/",
                "docs/",
                "examples/",
                "mcp-capability-router-skills/",
                "scripts/",
            )
        )
        or name == "tests/integration/test_examples.py"
    ]
    if unexpected:
        fail(f"the sdist contains unexpected files: {unexpected[:5]}")


def smoke_test(wheel: Path, version: str, python: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix="mcp-capability-router-smoke-"
    ) as directory:
        venv = Path(directory) / "venv"
        subprocess.run(
            ["uv", "venv", "--quiet", "--python", python, str(venv)], check=True
        )
        executable = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        install = ["uv", "pip", "install", "--quiet", "--python", str(executable)]
        subprocess.run([*install, str(wheel)], check=True)
        subprocess.run(
            [str(executable), *WARNING_OPTIONS, "-c", SMOKE_TEST, version],
            check=True,
            cwd=directory,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate built distributions.")
    parser.add_argument("dist", nargs="?", default="dist", type=Path)
    parser.add_argument(
        "--python",
        action="append",
        dest="pythons",
        help="Python version for the wheel smoke test; may be repeated",
    )
    arguments = parser.parse_args()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))["project"]
    version = project_version()
    wheels = sorted(arguments.dist.glob("mcp_capability_router-*.whl"))
    sdists = sorted(arguments.dist.glob("mcp_capability_router-*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        fail("expected exactly one wheel and one sdist")
    validate_wheel(wheels[0], version, project["requires-python"])
    validate_sdist(sdists[0])
    for python in arguments.pythons or ["3.12"]:
        smoke_test(wheels[0].resolve(), version, python)
    print("distribution validation passed")


if __name__ == "__main__":
    sys.exit(main())
