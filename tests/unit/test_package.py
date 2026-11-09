"""Tests of the public package surface."""

from __future__ import annotations

import subprocess
import sys

import mcp_capability_router

CORE_ONLY = """
import sys
import mcp_capability_router
from mcp_capability_router import gateway, retrieval
integrations = {"langchain", "langchain_core", "langgraph"}
print(",".join(sorted(name for name in sys.modules if name.split(".")[0] in integrations)))
"""


def test_exports_are_importable() -> None:
    for name in mcp_capability_router.__all__:
        assert getattr(mcp_capability_router, name) is not None


def test_core_imports_no_integration_or_extra() -> None:
    completed = subprocess.run(  # noqa: S603 - runs this interpreter on a fixed script
        [sys.executable, "-c", CORE_ONLY],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    assert completed.stdout.strip() == ""
