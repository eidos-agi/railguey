"""railguey — Project-scoped Railway management."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("railguey")
except PackageNotFoundError:
    __version__ = "dev"
