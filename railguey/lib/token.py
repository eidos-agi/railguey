"""Token discovery — account system first, then project .env files."""

from pathlib import Path


def _load_token(workspace: str) -> str:
    """Resolve a Railway token.

    Priority:
    1. Default account in ~/.railguey/accounts.json (set via railguey_account_default)
    2. RAILWAY_TOKEN in workspace/.env.local (then .env as fallback)

    This lets the account system override per-workspace tokens,
    so a single `railguey_account_default production` switches all
    tools to the production environment without touching .env files.
    """
    # 1. Account system
    try:
        from railguey.lib.accounts import get_account_token
        return get_account_token()
    except (ValueError, ImportError):
        pass

    # 2. Workspace .env files
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
        f"No Railway token found. Use railguey_account_add to register an account, "
        f"or add RAILWAY_TOKEN to {ws}/.env.local."
    )
