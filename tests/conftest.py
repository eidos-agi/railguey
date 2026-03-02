"""Shared pytest fixtures for railguey tests.

Fixtures are auto-discovered by pytest — no import needed in test files.
Helpers and constants live in tests/helpers.py (importable).
"""

import pytest

from tests.helpers import write_file


# ---------------------------------------------------------------------------
# Workspace fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path):
    """Bare temporary workspace directory — no files."""
    return tmp_path


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
