"""railguey — Project-scoped Railway MCP server."""

__version__ = "0.2.0"

from railguey.server import mcp


def run():
    """Entry point for the `railguey` console script."""
    mcp.run()
