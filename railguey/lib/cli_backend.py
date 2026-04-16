"""CLI backend — shells out to the Railway CLI with project-scoped tokens."""

import asyncio
import os
import shutil
from pathlib import Path

from railguey.lib.token import _load_token

_DEFAULT_TIMEOUT = 30
_LOGS_TIMEOUT = 60
_DEPLOY_TIMEOUT = 120


async def _run_railway(
    workspace: str,
    args: list[str],
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict:
    """Run a Railway CLI command with the project-scoped token.

    Sets RAILWAY_TOKEN in env and cwd to workspace so the CLI
    resolves any local railway.toml automatically.
    """
    railway = shutil.which("railway")
    if not railway:
        return {
            "error": "Railway CLI not found. Install it: https://docs.railway.com/guides/cli"
        }

    token = _load_token(workspace)
    env = {**os.environ, "RAILWAY_TOKEN": token}
    ws = str(Path(workspace).expanduser().resolve())

    try:
        proc = await asyncio.create_subprocess_exec(
            railway,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=ws,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        return {
            "error": f"Command timed out after {timeout}s: railway {' '.join(args)}"
        }
    except Exception as exc:
        return {"error": str(exc)}

    out = stdout.decode().strip() if stdout else ""
    err = stderr.decode().strip() if stderr else ""

    if proc.returncode != 0:
        return {
            "error": f"railway exited {proc.returncode}",
            "stderr": err,
            "output": out,
        }

    return {"output": out}
