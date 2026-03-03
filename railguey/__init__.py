"""railguey — Project-scoped Railway management."""

__version__ = "0.2.3"


def run():
    """Entry point for `railguey-mcp` console script (backward compat)."""
    from railguey.mcp import mcp
    mcp.run()
