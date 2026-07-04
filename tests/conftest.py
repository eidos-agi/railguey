"""Shared pytest fixtures for railguey tests.

Fixtures are auto-discovered by pytest — no import needed in test files.
Helpers and constants live in tests/helpers.py (importable).
"""

import pytest
from unittest.mock import patch

from tests.helpers import write_file


# ---------------------------------------------------------------------------
# Isolate tests from the host account system (~/.railguey/accounts.json)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_account_system():
    """Prevent tests from reading the real ~/.railguey/accounts.json."""
    with patch(
        "railguey.lib.accounts.get_account_token",
        side_effect=ValueError("No accounts configured (test isolation)"),
    ):
        yield


# ---------------------------------------------------------------------------
# Workspace fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """Bare temporary workspace directory — no files.

    Nested one level under tmp_path so its PARENT has no siblings: _load_token
    falls back to scanning sibling dirs for a shared RAILWAY_TOKEN, and pytest's
    per-test tmp_paths are siblings of each other — several carry a test
    `.env.local`. Returning bare tmp_path let that scan find those tokens, so the
    "no token" tests non-deterministically failed to raise. An isolated parent
    fixes it.
    """
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def workspace_with_token(tmp_path):
    """Workspace with a valid .env.local containing RAILWAY_TOKEN."""
    write_file(tmp_path / ".env.local", "RAILWAY_TOKEN=test-token-123\n")
    return tmp_path


@pytest.fixture
def workspace_healthy(tmp_path):
    """Workspace that passes all doctor checks (minus GraphQL)."""
    write_file(tmp_path / ".env.local", "RAILWAY_TOKEN=test-token-123\n")
    write_file(tmp_path / ".gitignore", "node_modules/\n.env.local\n")
    write_file(
        tmp_path / ".github" / "workflows" / "deploy.yml",
        "name: Deploy\nenv:\n  RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n"
        "run: railway up --service web --detach\n",
    )
    return tmp_path
