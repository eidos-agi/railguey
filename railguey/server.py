#!/usr/bin/env python3
"""railguey — Project-scoped Railway MCP server.

Reads RAILWAY_TOKEN from each project's .env.local so you never need
`railway login`. Every tool takes a `workspace` path and injects the
token into Railway CLI calls automatically.

Two backends coexist:
  - CLI: shells out to `railway` for operations that work well as commands
  - GraphQL: hits Backboard API directly for structured data and mutations
    the CLI doesn't expose (rollback, stop, cancel, etc.)

Each tool picks whichever backend fits best. Users don't need to care.

MIT licensed. FOSS under rhea-impact.
"""

import asyncio
import os
import shutil
from pathlib import Path
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("railguey")

# ---------------------------------------------------------------------------
# 1. Token Discovery
# ---------------------------------------------------------------------------

BACKBOARD_URL = "https://backboard.railway.com/graphql/v2"


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
# 2a. CLI Backend
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
# 2b. GraphQL Backend (Backboard API)
# ---------------------------------------------------------------------------


async def _gql(token: str, query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against Railway's Backboard API.

    Uses Project-Access-Token header (not Bearer) for project-scoped tokens.
    """
    headers = {
        "Content-Type": "application/json",
        "Project-Access-Token": token,
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(BACKBOARD_URL, headers=headers, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {"error": f"Backboard API returned {exc.response.status_code}", "body": exc.response.text}
        except httpx.RequestError as exc:
            return {"error": f"Request failed: {exc}"}

        data = resp.json()
        if "errors" in data:
            return {"error": "GraphQL error", "details": data["errors"]}
        return data.get("data", {})


async def _resolve_project(token: str) -> dict:
    """Introspect the project token to get projectId and environmentId."""
    result = await _gql(token, "query { projectToken { projectId environmentId } }")
    if "error" in result:
        return result
    return result.get("projectToken", {})


async def _resolve_service_id(token: str, project_id: str, service_name: str) -> str | None:
    """Resolve a service name to its ID within a project."""
    query = """
    query project($id: String!) {
      project(id: $id) {
        services { edges { node { id name } } }
      }
    }
    """
    result = await _gql(token, query, {"id": project_id})
    if "error" in result:
        return None
    edges = result.get("project", {}).get("services", {}).get("edges", [])
    for edge in edges:
        node = edge.get("node", {})
        if node.get("name", "").lower() == service_name.lower():
            return node["id"]
    return None


# ---------------------------------------------------------------------------
# 3. Tools — CLI backend
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
# 4. Tools — GraphQL backend
# ---------------------------------------------------------------------------


@mcp.tool()
async def railguey_deployments(
    workspace: str,
    service: str,
    limit: int = 10,
) -> dict:
    """List recent deployments for a service with IDs, statuses, and timestamps.

    Uses the Backboard GraphQL API for structured data. No CLI needed.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
        limit: Number of deployments to return (default 10).
    """
    token = _load_token(workspace)

    project = await _resolve_project(token)
    if "error" in project:
        return project
    project_id = project.get("projectId")
    if not project_id:
        return {"error": "Could not resolve projectId from token"}

    service_id = await _resolve_service_id(token, project_id, service)
    if not service_id:
        return {"error": f"Service '{service}' not found in project"}

    query = """
    query deployments($input: DeploymentListInput!, $first: Int) {
      deployments(input: $input, first: $first) {
        edges {
          node {
            id
            status
            createdAt
            url
            staticUrl
            canRedeploy
            canRollback
          }
        }
      }
    }
    """
    variables = {
        "input": {"projectId": project_id, "serviceId": service_id},
        "first": limit,
    }
    result = await _gql(token, query, variables)
    if "error" in result:
        return result

    edges = result.get("deployments", {}).get("edges", [])
    deployments = [edge["node"] for edge in edges]
    return {"deployments": deployments, "count": len(deployments)}


@mcp.tool()
async def railguey_rollback(workspace: str, service: str, deployment_id: str) -> dict:
    """Roll back a service to a specific previous deployment.

    This is a GraphQL-only operation — the Railway CLI doesn't support it.
    Use railguey_deployments first to find the deployment ID to roll back to.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name (used for confirmation context).
        deployment_id: The deployment ID to roll back to (from railguey_deployments).
    """
    token = _load_token(workspace)
    query = """
    mutation deploymentRollback($id: String!) {
      deploymentRollback(id: $id) { id status }
    }
    """
    return await _gql(token, query, {"id": deployment_id})


@mcp.tool()
async def railguey_service_info(workspace: str, service: str) -> dict:
    """Get detailed configuration for a Railway service.

    Returns build command, start command, healthcheck, region, replicas,
    restart policy, and latest deployment status. Useful for debugging
    deploy issues or auditing service config.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
    """
    token = _load_token(workspace)
    project = await _resolve_project(token)
    if "error" in project:
        return project
    project_id = project.get("projectId")
    environment_id = project.get("environmentId")
    if not project_id or not environment_id:
        return {"error": "Could not resolve projectId/environmentId from token"}

    service_id = await _resolve_service_id(token, project_id, service)
    if not service_id:
        return {"error": f"Service '{service}' not found in project"}

    query = """
    query serviceInstance($serviceId: String!, $environmentId: String!) {
      serviceInstance(serviceId: $serviceId, environmentId: $environmentId) {
        id
        serviceName
        startCommand
        buildCommand
        rootDirectory
        healthcheckPath
        region
        numReplicas
        restartPolicyType
        restartPolicyMaxRetries
        latestDeployment { id status createdAt url }
      }
    }
    """
    result = await _gql(token, query, {
        "serviceId": service_id,
        "environmentId": environment_id,
    })
    if "error" in result:
        return result
    return result.get("serviceInstance", {})


@mcp.tool()
async def railguey_http_logs(
    workspace: str,
    service: str,
    deployment_id: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Get HTTP request logs for a service — status codes, latency, paths.

    This is a GraphQL-only feature the CLI doesn't expose. Useful for
    debugging 5xx errors, slow endpoints, or traffic patterns.

    If no deployment_id is provided, fetches the latest deployment's logs.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
        deployment_id: Optional specific deployment ID. Defaults to latest.
        limit: Number of log entries to return (default 50).
    """
    token = _load_token(workspace)

    if not deployment_id:
        project = await _resolve_project(token)
        if "error" in project:
            return project
        project_id = project.get("projectId")
        service_id = await _resolve_service_id(token, project_id, service)
        if not service_id:
            return {"error": f"Service '{service}' not found in project"}

        # Get the latest deployment ID
        dep_query = """
        query deployments($input: DeploymentListInput!) {
          deployments(input: $input, first: 1) {
            edges { node { id } }
          }
        }
        """
        dep_result = await _gql(token, dep_query, {
            "input": {"projectId": project_id, "serviceId": service_id}
        })
        if "error" in dep_result:
            return dep_result
        edges = dep_result.get("deployments", {}).get("edges", [])
        if not edges:
            return {"error": f"No deployments found for service '{service}'"}
        deployment_id = edges[0]["node"]["id"]

    query = """
    query httpLogs($deploymentId: String!, $limit: Int) {
      httpLogs(deploymentId: $deploymentId, limit: $limit) {
        timestamp
        requestId
        method
        path
        httpStatus
        totalDuration
        srcIp
      }
    }
    """
    result = await _gql(token, query, {"deploymentId": deployment_id, "limit": limit})
    if "error" in result:
        return result
    logs = result.get("httpLogs", [])
    return {"logs": logs, "count": len(logs), "deployment_id": deployment_id}


@mcp.tool()
async def railguey_unlink_repo(workspace: str, service: str) -> dict:
    """Disconnect a service from its linked GitHub repo.

    Railway's GitHub repo linking auto-deploys on push, but has been
    unreliable (missed webhooks, silent failures). This tool disconnects
    the integration so you can use token-based CI/CD instead.

    After unlinking, use railguey_doctor to set up GitHub Actions CI/CD.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name to disconnect from GitHub.
    """
    token = _load_token(workspace)
    project = await _resolve_project(token)
    if "error" in project:
        return project
    project_id = project.get("projectId")

    service_id = await _resolve_service_id(token, project_id, service)
    if not service_id:
        return {"error": f"Service '{service}' not found in project"}

    query = """
    mutation serviceDisconnect($id: String!) {
      serviceDisconnect(id: $id) { id }
    }
    """
    result = await _gql(token, query, {"id": service_id})
    if "error" in result:
        return result
    return {
        "disconnected": True,
        "service": service,
        "next_step": (
            "GitHub repo linking removed. Deploys will no longer auto-trigger on push. "
            "Run railguey_doctor to set up token-based GitHub Actions CI/CD instead."
        ),
    }


# ---------------------------------------------------------------------------
# 5. Doctor — opinionated workspace audit
# ---------------------------------------------------------------------------


@mcp.tool()
async def railguey_doctor(workspace: str) -> dict:
    """Audit a workspace for Railway deployment best practices.

    Checks for:
    - RAILWAY_TOKEN in .env.local (required)
    - .env.local in .gitignore (security)
    - GitHub Actions deploy workflow (recommended over repo linking)
    - Whether services are linked to GitHub repos (discouraged — brittle)

    Returns a structured report with findings and actionable fixes.

    Args:
        workspace: Absolute path to project directory to audit.
    """
    ws = Path(workspace).expanduser().resolve()
    findings = []
    score = 0
    max_score = 0

    # --- Check 1: RAILWAY_TOKEN exists ---
    max_score += 1
    has_token = False
    try:
        _load_token(workspace)
        has_token = True
        score += 1
        findings.append({
            "check": "RAILWAY_TOKEN",
            "status": "pass",
            "message": "Found in .env.local or .env",
        })
    except ValueError:
        findings.append({
            "check": "RAILWAY_TOKEN",
            "status": "fail",
            "message": "Not found. Add RAILWAY_TOKEN=<your-project-token> to .env.local",
            "fix": "Get a project token from Railway dashboard → Project → Settings → Tokens",
        })

    # --- Check 2: .env.local in .gitignore ---
    max_score += 1
    gitignore = ws / ".gitignore"
    env_ignored = False
    if gitignore.is_file():
        content = gitignore.read_text()
        env_ignored = any(
            line.strip() in (".env.local", ".env*", ".env.*", "*.env.local")
            for line in content.splitlines()
        )
    if env_ignored:
        score += 1
        findings.append({
            "check": ".gitignore",
            "status": "pass",
            "message": ".env.local is gitignored",
        })
    else:
        findings.append({
            "check": ".gitignore",
            "status": "warn",
            "message": ".env.local may not be gitignored — token could leak",
            "fix": "Add .env.local to your .gitignore file",
        })

    # --- Check 3: GitHub Actions deploy workflow ---
    max_score += 1
    workflows_dir = ws / ".github" / "workflows"
    has_deploy_workflow = False
    if workflows_dir.is_dir():
        for f in workflows_dir.iterdir():
            if f.suffix in (".yml", ".yaml") and f.is_file():
                content = f.read_text()
                if "railway" in content.lower() and "RAILWAY_TOKEN" in content:
                    has_deploy_workflow = True
                    break
    if has_deploy_workflow:
        score += 1
        findings.append({
            "check": "CI/CD workflow",
            "status": "pass",
            "message": "GitHub Actions workflow found with RAILWAY_TOKEN",
        })
    else:
        findings.append({
            "check": "CI/CD workflow",
            "status": "warn",
            "message": "No GitHub Actions deploy workflow found",
            "fix": (
                "Add .github/workflows/deploy.yml using the project token pattern. "
                "See: https://github.com/rhea-impact/railguey/tree/main/examples"
            ),
        })

    # --- Check 4: GitHub repo linking (check via GraphQL if token exists) ---
    max_score += 1
    if has_token:
        token = _load_token(workspace)
        project = await _resolve_project(token)
        if "error" not in project:
            project_id = project.get("projectId")
            query = """
            query project($id: String!) {
              project(id: $id) {
                services {
                  edges {
                    node { id name }
                  }
                }
              }
            }
            """
            result = await _gql(token, query, {"id": project_id})
            if "error" not in result:
                # Check each service for source connection
                edges = result.get("project", {}).get("services", {}).get("edges", [])
                linked_services = []
                for edge in edges:
                    svc = edge.get("node", {})
                    svc_id = svc.get("id")
                    svc_name = svc.get("name", "unknown")
                    # Query service details for source info
                    svc_query = """
                    query service($id: String!) {
                      service(id: $id) { id name repoTriggers { repository branch } }
                    }
                    """
                    svc_result = await _gql(token, svc_query, {"id": svc_id})
                    if "error" not in svc_result:
                        triggers = svc_result.get("service", {}).get("repoTriggers", [])
                        if triggers:
                            linked_services.append({
                                "service": svc_name,
                                "repo": triggers[0].get("repository", "unknown"),
                            })

                if linked_services:
                    findings.append({
                        "check": "GitHub repo linking",
                        "status": "warn",
                        "message": f"{len(linked_services)} service(s) linked to GitHub repos (brittle auto-deploy)",
                        "linked": linked_services,
                        "fix": (
                            "Consider disconnecting with railguey_unlink_repo and using "
                            "GitHub Actions CI/CD instead. Repo linking has been unreliable."
                        ),
                    })
                else:
                    score += 1
                    findings.append({
                        "check": "GitHub repo linking",
                        "status": "pass",
                        "message": "No services linked to GitHub repos (good — using token-based deploys)",
                    })
            else:
                findings.append({
                    "check": "GitHub repo linking",
                    "status": "skip",
                    "message": "Could not query project (API error)",
                })
        else:
            findings.append({
                "check": "GitHub repo linking",
                "status": "skip",
                "message": "Could not resolve project from token",
            })
    else:
        findings.append({
            "check": "GitHub repo linking",
            "status": "skip",
            "message": "No token — cannot check repo linking",
        })

    return {
        "score": f"{score}/{max_score}",
        "findings": findings,
        "healthy": score == max_score,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
