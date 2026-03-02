"""MCP server — thin wrappers that delegate to railguey.lib.tools.

Tool names keep the railguey_ prefix for MCP (AI agents need namespaced tool names).
"""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from railguey.lib import tools

mcp = FastMCP("railguey")


@mcp.tool()
async def railguey_status(workspace: str) -> dict:
    """Show status of all services in the Railway project.

    Args:
        workspace: Absolute path to a project directory containing .env.local
                   with RAILWAY_TOKEN.
    """
    return await tools.status(workspace)


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
    return await tools.logs(workspace, service, lines, build, filter)


@mcp.tool()
async def railguey_deploy(workspace: str, service: str) -> dict:
    """Trigger a deploy for a Railway service (non-blocking).

    Always uses --detach so the tool returns immediately.
    The deploy continues in the background on Railway.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name to deploy.
    """
    return await tools.deploy(workspace, service)


@mcp.tool()
async def railguey_variables(workspace: str, service: str) -> dict:
    """List environment variables for a Railway service.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
    """
    return await tools.variables(workspace, service)


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
    return await tools.variable_set(workspace, service, key, value)


@mcp.tool()
async def railguey_services(workspace: str) -> dict:
    """List all services in the Railway project with deployment status.

    Args:
        workspace: Absolute path to project directory with .env.local.
    """
    return await tools.services(workspace)


@mcp.tool()
async def railguey_redeploy(workspace: str, service: str) -> dict:
    """Redeploy the latest deployment of a service (rebuilds from source).

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
    """
    return await tools.redeploy(workspace, service)


@mcp.tool()
async def railguey_restart(workspace: str, service: str) -> dict:
    """Restart the latest deployment of a service (no rebuild).

    Faster than redeploy — just restarts the container.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
    """
    return await tools.restart(workspace, service)


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
    return await tools.domain(workspace, service, domain, port)


@mcp.tool()
async def railguey_environment_create(workspace: str, name: str) -> dict:
    """Create a new environment in the Railway project.

    Args:
        workspace: Absolute path to project directory with .env.local.
        name: Name for the new environment (e.g. "staging", "preview").
    """
    return await tools.environment_create(workspace, name)


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
    return await tools.deployments(workspace, service, limit)


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
    return await tools.rollback(workspace, service, deployment_id)


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
    return await tools.service_info(workspace, service)


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
    return await tools.http_logs(workspace, service, deployment_id, limit)


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
    return await tools.unlink_repo(workspace, service)


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
    return await tools.doctor(workspace)


if __name__ == "__main__":
    mcp.run()
