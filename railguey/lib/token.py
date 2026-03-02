"""Token discovery — reads RAILWAY_TOKEN from project .env files."""

from pathlib import Path


def _load_token(workspace: str) -> str:
    """Read RAILWAY_TOKEN from workspace/.env.local (then .env as fallback).

    Simple line parser — no python-dotenv dependency needed.
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
        f"RAILWAY_TOKEN not found in {ws}/.env.local or {ws}/.env — "
        f"add it to the project's .env.local file."
    )
