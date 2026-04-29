"""railguey.lib — shared core with no framework dependencies.

railguey never invokes the `railway` CLI. Not internally, not as a fallback,
not from any code path. All Railway operations go through the Backboard
GraphQL API. See `mcp.py` INSTRUCTIONS for the rule and rationale.
"""

from railguey.lib.token import _load_token
from railguey.lib.graphql import (
    _gql,
    _resolve_project,
    _resolve_service_id,
    BACKBOARD_URL,
)
from railguey.lib import tools

__all__ = [
    "_load_token",
    "_gql",
    "_resolve_project",
    "_resolve_service_id",
    "BACKBOARD_URL",
    "tools",
]
