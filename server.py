#!/usr/bin/env python3
"""railguey — Project-scoped Railway MCP server.

Reads RAILWAY_TOKEN from each project's .env.local so you never need
`railway login`. Every tool takes a `workspace` path and injects the
token into Railway CLI calls automatically.

MIT licensed. FOSS under rhea-impact.
"""

import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("railguey")

# ---------------------------------------------------------------------------
# 1. Token Discovery
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 2. Subprocess Runner
# ---------------------------------------------------------------------------

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
        return {"error": "Railway CLI not found. Install it: https://docs.railway.com/guides/cli"}

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
        return {"error": f"Command timed out after {timeout}s: railway {' '.join(args)}"}
    except Exception as exc:
        return {"error": str(exc)}

    out = stdout.decode().strip() if stdout else ""
    err = stderr.decode().strip() if stderr else ""

    if proc.returncode != 0:
        return {"error": f"railway exited {proc.returncode}", "stderr": err, "output": out}

    return {"output": out}


# ---------------------------------------------------------------------------
# 3. Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def railguey_status(workspace: str) -> dict:
    """Show status of all services in the Railway project.

    Args:
        workspace: Absolute path to a project directory containing .env.local
                   with RAILWAY_TOKEN.
    """
    return await _run_railway(workspace, ["status", "--json"])


@mcp.tool()
async def railguey_logs(
    workspace: str,
    service: str,
    lines: int = 100,
    build: bool = False,
    filter: Optional[str] = None,
) -> dict:
    """Fetch recent logs from a Railway service.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name (e.g. "cerebro", "data-daemon").
        lines: Number of log lines to return (default 100).
        build: If True, show build logs instead of deploy logs.
        filter: Optional string to filter log lines.
    """
    args = ["logs", "--service", service, "--lines", str(lines)]
    if build:
        args.append("--build")
    if filter:
        args.extend(["--filter", filter])
    return await _run_railway(workspace, args, timeout=_LOGS_TIMEOUT)


@mcp.tool()
async def railguey_deploy(workspace: str, service: str) -> dict:
    """Trigger a deploy for a Railway service (non-blocking).

    Always uses --detach so the tool returns immediately.
    The deploy continues in the background on Railway.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name to deploy.
    """
    return await _run_railway(
        workspace, ["up", "--service", service, "--detach"], timeout=_DEPLOY_TIMEOUT
    )


@mcp.tool()
async def railguey_variables(workspace: str, service: str) -> dict:
    """List environment variables for a Railway service.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
    """
    return await _run_railway(workspace, ["variables", "--service", service, "--json"])


@mcp.tool()
async def railguey_variable_set(
    workspace: str,
    service: str,
    key: str,
    value: str,
) -> dict:
    """Set an environment variable on a Railway service.

    NOTE: This will trigger a redeploy of the service.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
        key: Variable name (e.g. "DATABASE_URL").
        value: Variable value.
    """
    return await _run_railway(
        workspace, ["variables", "--set", f"{key}={value}", "--service", service]
    )


@mcp.tool()
async def railguey_services(workspace: str) -> dict:
    """List all services in the Railway project with deployment status.

    Args:
        workspace: Absolute path to project directory with .env.local.
    """
    return await _run_railway(workspace, ["service", "status"])


@mcp.tool()
async def railguey_deployments(workspace: str, service: str) -> dict:
    """List recent deployments for a service with IDs, statuses, and metadata.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
    """
    return await _run_railway(workspace, ["deployment", "list", "--service", service])


@mcp.tool()
async def railguey_redeploy(workspace: str, service: str) -> dict:
    """Redeploy the latest deployment of a service (rebuilds from source).

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
    """
    return await _run_railway(
        workspace, ["redeploy", "--service", service, "--yes", "--json"]
    )


@mcp.tool()
async def railguey_restart(workspace: str, service: str) -> dict:
    """Restart the latest deployment of a service (no rebuild).

    Faster than redeploy — just restarts the container.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
    """
    return await _run_railway(
        workspace, ["restart", "--service", service, "--yes", "--json"]
    )


@mcp.tool()
async def railguey_domain(
    workspace: str,
    service: str,
    domain: Optional[str] = None,
    port: Optional[int] = None,
) -> dict:
    """Generate a railway.app domain or add a custom domain to a service.

    If no domain is specified, generates a railway-provided domain.
    If a custom domain is specified, returns the DNS records to configure.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
        domain: Optional custom domain (e.g. "api.example.com"). Omit to auto-generate.
        port: Optional port to bind the domain to.
    """
    args = ["domain", "--service", service, "--json"]
    if domain:
        args.append(domain)
    if port is not None:
        args.extend(["--port", str(port)])
    return await _run_railway(workspace, args)


@mcp.tool()
async def railguey_environment_create(workspace: str, name: str) -> dict:
    """Create a new environment in the Railway project.

    Args:
        workspace: Absolute path to project directory with .env.local.
        name: Name for the new environment (e.g. "staging", "preview").
    """
    return await _run_railway(workspace, ["environment", "new", name])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
