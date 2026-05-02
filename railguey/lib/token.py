"""Token discovery from workspace .env files."""

from pathlib import Path


def _load_project_token(workspace: str) -> str:
    """Resolve a PROJECT-scoped Railway token from workspace .env files.

    railguey is intentionally workspace-scoped: the CLI reads the token from
    the workspace it was asked to operate on instead of consulting global
    account state. That keeps CI and agents deterministic.
    """
    ws = Path(workspace).expanduser().resolve()
    for filename in (".env.local", ".env"):
        envfile = ws / filename
        if not envfile.is_file():
            continue
        for line in envfile.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("RAILWAY_TOKEN="):
                value = stripped.split("=", 1)[1].strip()
                # Strip surrounding quotes if present
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if value:
                    return value
    raise ValueError(
        f"No project-scoped Railway token found. Add RAILWAY_TOKEN to {ws}/.env.local."
    )


def _load_token(workspace: str) -> str:
    """Resolve a Railway token from workspace/.env.local or workspace/.env."""
    return _load_project_token(workspace)
