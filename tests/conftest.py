"""Shared test configuration."""

from __future__ import annotations

import logging
import os

from hypothesis import HealthCheck, settings

settings.register_profile("dev", max_examples=100, deadline=None)
settings.register_profile(
    "ci",
    max_examples=400,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))

# In-process FastMCP servers log the tracebacks of tools that fail on purpose.
logging.getLogger("fastmcp").setLevel(logging.CRITICAL)
