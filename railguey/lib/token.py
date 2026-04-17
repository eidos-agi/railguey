"""Token discovery — account override, then workspace .env files."""

from pathlib import Path


def _load_project_token(workspace: str) -> str:
    """Resolve a PROJECT-scoped Railway token from workspace .env files.

    Skips the account system entirely. Some Railway GraphQL mutations
    (volumeCreate, volumeDelete, volumeInstanceUpdate) require a
    project-scoped token and reject account tokens with
    "Project Token not found" — for those, call this function instead
    of _load_token.
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
    """Resolve a Railway token.

    Priority:
    1. Default account in ~/.railguey/accounts.json (if one is set)
    2. RAILWAY_TOKEN in workspace/.env.local (then .env as fallback)

    The account system acts as an explicit override — when you call
    railguey_account_default('production'), ALL tools switch to the
    production token regardless of what's in .env.local. This is the
    core use case: briefly operate on a different environment without
    swapping .env files.

    When no account is configured, falls back to workspace .env files.

    NOTE: Volume mutations require a project-scoped token — use
    _load_project_token() instead for those.
    """
    # 1. Account system override
    try:
        from railguey.lib.accounts import get_account_token

        return get_account_token()
    except (ValueError, ImportError):
        pass

    # 2. Workspace .env files (fall back to project-token reader)
    return _load_project_token(workspace)
