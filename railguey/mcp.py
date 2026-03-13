"""MCP server — thin wrappers that delegate to railguey.lib.tools.

Tool names keep the railguey_ prefix for MCP (AI agents need namespaced tool names).
"""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from railguey.lib import tools
from railguey.lib import accounts
from railguey.lib import totp
from railguey.lib import orchestrate

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

    TIP: Use the filter param to cut through noise. For build failures,
    try filter="error" or filter="supabase". The filter runs server-side
    so you only get matching lines back — much faster than scanning 100+ entries.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name (e.g. "cerebro", "data-daemon").
        lines: Number of log lines to return (default 100).
        build: If True, show build logs instead of deploy logs.
        filter: Server-side filter string — use to narrow logs (e.g. "error", "timeout", "ECONNREFUSED").
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
async def railguey_deployment_logs(
    workspace: str,
    deployment_id: str,
    limit: int = 100,
    build: bool = False,
    filter: Optional[str] = None,
) -> dict:
    """Get logs for a specific deployment by ID.

    Use railguey_deployments to find deployment IDs first. This tool lets
    you inspect any deployment — not just the latest — which is essential
    when debugging across multiple environments or services.

    TIP: Use the filter param to cut through noise. For build failures,
    try filter="error" or filter="supabase". The filter runs server-side
    so you only get matching lines back.

    Args:
        workspace: Absolute path to project directory with .env.local.
        deployment_id: The deployment ID (from railguey_deployments).
        limit: Number of log lines to return (default 100).
        build: If True, show build logs instead of deploy logs.
        filter: Server-side filter string — use to narrow logs (e.g. "error", "timeout", "ECONNREFUSED").
    """
    return await tools.deployment_logs(workspace, deployment_id, limit, build, filter)


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
    """Full workspace audit — workspace + service + project checks combined.

    Three layers:
      - Workspace: local filesystem (token, .gitignore, Dockerfile, CI/CD workflow, git, lockfile)
      - Service: THIS service's Railway health (deployment status, domain, deploy drift)
      - Project: whole Railway project (cross-service issues, informational)

    Workspace issues affect your score. Service issues affect your score.
    Project issues are informational — other services' problems don't tank your score.

    Returns structured report with separate scores per layer + remediation.

    Args:
        workspace: Absolute path to project directory to audit.
    """
    from railguey.lib.doctor import doctor
    return await doctor(workspace)


@mcp.tool()
async def railguey_doctor_service_level(workspace: str, service: str | None = None) -> dict:
    """Check a single service's Railway deployment health.

    Checks:
      1. This service's latest deployment status
      2. This service's domain configuration
      3. Deploy drift (local code vs this service's deploy time)
      4. Token scope vs workflow environment targets
      5. Workflow environment names match Railway environments

    Auto-detects service name from workflow, .env.local, or directory name.

    Args:
        workspace: Absolute path to project directory.
        service: Service name (auto-detected if omitted).
    """
    from railguey.lib.doctor import doctor_service_level
    return await doctor_service_level(workspace, service)


@mcp.tool()
async def railguey_doctor_project_level(workspace: str) -> dict:
    """Check the entire Railway project's health (all services).

    Checks:
      1. Repo linking across all services
      2. Failed deployments across all services
      3. Domain coverage across all services
      4. Deploy drift across all services

    These are informational — other services' problems are reported but
    don't affect any single workspace's score.

    Args:
        workspace: Absolute path to project directory (for token).
    """
    from railguey.lib.doctor import doctor_project_level
    return await doctor_project_level(workspace)


@mcp.tool()
async def railguey_account_add(name: str, token: str, email: Optional[str] = None) -> dict:
    """Register a Railway account token for multi-account support.

    Store tokens from multiple Railway accounts. Each gets a name you
    reference later (e.g., "aic", "eidos", "personal").

    Get tokens from: Railway Dashboard → Account Settings → Tokens → Create.

    Args:
        name: Short name for this account (e.g., "aic", "eidos").
        token: Railway API token (starts with rw_ or similar).
        email: Email associated with this Railway account.
    """
    return accounts.add_account(name, token, email)


@mcp.tool()
async def railguey_account_remove(name: str) -> dict:
    """Remove a stored Railway account.

    Args:
        name: Account name to remove.
    """
    return accounts.remove_account(name)


@mcp.tool()
async def railguey_accounts() -> dict:
    """List all stored Railway accounts and their workspaces.

    Shows which accounts are configured and which is the default.
    Use railguey_account_add to register new accounts.
    """
    return accounts.list_accounts()


@mcp.tool()
async def railguey_account_default(name: str) -> dict:
    """Set the default Railway account for operations.

    Args:
        name: Account name to make default.
    """
    return accounts.set_default_account(name)


@mcp.tool()
async def railguey_workspaces(account: Optional[str] = None) -> dict:
    """List workspaces (teams) available to a Railway account.

    ALWAYS call this before creating a project to pick the right team.
    Returns workspace names and IDs.

    Args:
        account: Account name (uses default if not specified).
    """
    return await tools.list_workspaces(account)


@mcp.tool()
async def railguey_project_create(
    name: str,
    team_id: str,
    workspace: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Create a new Railway project in a specific team/workspace.

    REQUIRES team_id — will NEVER create a project without an explicit team.
    This prevents accidental creation in personal accounts.

    Workflow:
    1. Call railguey_workspaces() to list available teams
    2. Pick the right team_id
    3. Call this with the team_id

    Args:
        name: Name for the new Railway project.
        team_id: Railway workspace/team ID (REQUIRED). Get from railguey_workspaces().
        workspace: Optional absolute path to project directory. If provided,
                   writes RAILWAY_TOKEN to .env.local for immediate use.
        account: Account name (uses default if not specified).
    """
    return await tools.project_create(name, team_id, workspace, account)


@mcp.tool()
async def railguey_projects(team_id: str, account: Optional[str] = None) -> dict:
    """List all projects in a Railway workspace/team.

    Use railguey_workspaces first to get the team_id.

    Args:
        team_id: Railway workspace/team ID.
        account: Account name (uses default if not specified).
    """
    return await tools.list_projects(team_id, account)


@mcp.tool()
async def railguey_project_delete(
    project_id: str,
    totp_code: str,
    account: Optional[str] = None,
) -> dict:
    """Delete a Railway project. This is IRREVERSIBLE. Requires TOTP.

    You MUST provide your current TOTP code from your authenticator app.
    Set up TOTP first with railguey_totp_setup.

    Args:
        project_id: Railway project ID to delete.
        totp_code: Current 6-digit TOTP code (REQUIRED).
        account: Account name (uses default if not specified).
    """
    error = totp.require_totp(totp_code)
    if error:
        return error
    return await tools.project_delete(project_id, account)


@mcp.tool()
async def railguey_project_transfer(
    project_id: str,
    target_team_id: str,
    totp_code: str,
    account: Optional[str] = None,
) -> dict:
    """Transfer a project to a different team/workspace. Requires TOTP.

    Use this to move a project that was accidentally created in the wrong team.
    You MUST provide your current TOTP code from your authenticator app.

    Args:
        project_id: Railway project ID to transfer.
        target_team_id: Destination workspace/team ID. Get from railguey_workspaces().
        totp_code: Current 6-digit TOTP code (REQUIRED).
        account: Account name (uses default if not specified).
    """
    error = totp.require_totp(totp_code)
    if error:
        return error
    return await tools.project_transfer(project_id, target_team_id, account)


@mcp.tool()
async def railguey_totp_setup() -> dict:
    """Generate a TOTP secret for this machine.

    Creates a unique secret stored at ~/.railguey/totp_secret.
    Returns a provisioning URI you can add to your authenticator app
    (1Password, Authy, Google Authenticator).

    Required before using destructive operations (delete, transfer).
    """
    return totp.setup()


@mcp.tool()
async def railguey_totp_verify(code: str) -> dict:
    """Test that your TOTP code is working.

    Args:
        code: Current 6-digit code from your authenticator app.
    """
    return totp.verify(code)


@mcp.tool()
async def railguey_service_update(
    workspace: str,
    service: str,
    healthcheck_path: Optional[str] = None,
    start_command: Optional[str] = None,
    build_command: Optional[str] = None,
    root_directory: Optional[str] = None,
    region: Optional[str] = None,
    num_replicas: Optional[int] = None,
    restart_policy_type: Optional[str] = None,
    restart_policy_max_retries: Optional[int] = None,
) -> dict:
    """Update service instance settings like healthcheck, commands, region, and replicas.

    This modifies service configuration without triggering a redeploy.
    Use railguey_service_info to see current settings first.

    REQUIRES an account token (railguey_account_add) — project tokens cannot
    execute this mutation. The tool auto-detects the right account.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
        healthcheck_path: Healthcheck endpoint path (e.g. "/health").
        start_command: Command to start the service (e.g. "node server.js").
        build_command: Command to build the service (e.g. "npm run build").
        root_directory: Root directory for the service source.
        region: Deployment region (e.g. "us-west1").
        num_replicas: Number of replicas to run.
        restart_policy_type: Restart policy ("ON_FAILURE", "ALWAYS", or "NEVER").
        restart_policy_max_retries: Max restart retries (used with ON_FAILURE).
    """
    return await tools.service_update(
        workspace, service,
        healthcheck_path=healthcheck_path,
        start_command=start_command,
        build_command=build_command,
        root_directory=root_directory,
        region=region,
        num_replicas=num_replicas,
        restart_policy_type=restart_policy_type,
        restart_policy_max_retries=restart_policy_max_retries,
    )


@mcp.tool()
async def railguey_service_create(workspace: str, name: str) -> dict:
    """Create a new empty service in a Railway project.

    After creation, the service exists but has no deployments.
    Use railguey_deploy or connect a GitHub repo to trigger the first build.

    Args:
        workspace: Absolute path to project directory with .env.local.
        name: Name for the new service.
    """
    return await tools.service_create(workspace, name)


# ── Orchestration tools ─────────────────────────────────────────────


@mcp.tool()
async def railguey_registry(service: Optional[str] = None) -> dict:
    """Read the service registry. Returns deploy config, dependencies, and health
    definitions for one or all services.

    Use this before deploying to understand branch mappings, dependency gates,
    and verification requirements.

    Args:
        service: Optional service name. If omitted, returns all services.
    """
    return await orchestrate.registry(service)


@mcp.tool()
async def railguey_preflight(service: str, workspace: Optional[str] = None) -> dict:
    """Pre-push verification for a service. Returns go/no-go with reasons.

    Checks: correct branch, clean worktree, no in-progress deploys,
    required dependencies deployed. Run this BEFORE pushing code.

    Args:
        service: Service name from the registry (e.g. "data-daemon", "cerebro").
        workspace: Optional workspace path override. Uses registry default if omitted.
    """
    return await orchestrate.preflight(service, workspace)


@mcp.tool()
async def railguey_verify(
    service: str,
    workspace: Optional[str] = None,
    deployment_id: Optional[str] = None,
) -> dict:
    """Post-push verification. Polls Railway deploy status, checks health
    endpoint, scans logs for fail-fast patterns.

    Run this AFTER pushing code. Will poll until the deploy reaches a terminal
    state (SUCCESS/FAILED), then run health probes and log scanning.

    Args:
        service: Service name from the registry.
        workspace: Optional workspace path override.
        deployment_id: Optional specific deployment ID to verify.
    """
    return await orchestrate.verify(service, workspace, deployment_id)


@mcp.tool()
async def railguey_deploy_plan(repos: list[str]) -> dict:
    """Generate an ordered deploy plan for changed repos.

    Maps repos to affected services, expands dependencies, and produces
    a staged execution plan:
      Stage 1: Database migrations (blocking gate)
      Stage 2: API/config services (verify before proceeding)
      Stage 3: Frontends and workers (parallel where safe)

    Args:
        repos: List of repo names with changes (e.g. ["data-daemon", "cerebro-migrations"]).
    """
    return await orchestrate.deploy_plan(repos)


if __name__ == "__main__":
    mcp.run()
