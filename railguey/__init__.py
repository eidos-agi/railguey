"""railguey — Project-scoped Railway management."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("railguey")
except PackageNotFoundError:
    __version__ = "dev"


def run():
    """Entry point for `railguey-mcp` console script (backward compat)."""
    from railguey.mcp import mcp

    mcp.run()
