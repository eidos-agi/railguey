"""Shared test helpers and constants — importable by test modules."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# File helper
# ---------------------------------------------------------------------------


def write_file(path: Path, content: str):
    """Write content to a file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


# ---------------------------------------------------------------------------
# httpx mock helpers (for GraphQL backend tests)
# ---------------------------------------------------------------------------


def mock_httpx_response(json_data, status_code=200):
    """Create a mock httpx.Response with sync .json() method."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def mock_httpx_client(response):
    """Create a mock httpx.AsyncClient that returns the given response on POST."""
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ---------------------------------------------------------------------------
# CLI mock helpers
# ---------------------------------------------------------------------------


def mock_railway_proc(stdout=b"ok", stderr=b"", returncode=0):
    """Create a mock asyncio subprocess for Railway CLI tests."""
    proc = AsyncMock()
    proc.communicate.return_value = (stdout, stderr)
    proc.returncode = returncode
    return proc


# ---------------------------------------------------------------------------
# GraphQL test constants
# ---------------------------------------------------------------------------

PROJECT_DATA = {"projectId": "proj-abc", "environmentId": "env-xyz"}

SERVICES_DATA = {
    "project": {
        "services": {
            "edges": [
                {"node": {"id": "svc-111", "name": "web"}},
                {"node": {"id": "svc-222", "name": "worker"}},
            ]
        }
    }
}
