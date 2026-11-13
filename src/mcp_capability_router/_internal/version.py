"""The installed version of the package."""

from importlib.metadata import PackageNotFoundError, version

try:
    VERSION = version("mcp-capability-router")
except PackageNotFoundError:  # pragma: no cover - only without installed metadata
    VERSION = "0.0.0"
