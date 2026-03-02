"""17 pure async tool functions — no framework decorators, no prefixes.

Usage:
    from railguey.lib import tools
    result = await tools.status("/path/to/workspace")
"""

from typing import Optional

from railguey.lib.token import _load_token
from railguey.lib.cli_backend import _run_railway, _LOGS_TIMEOUT, _DEPLOY_TIMEOUT
from railguey.lib.graphql import _gql, _resolve_project, _resolve_service_id
from railguey.lib.doctor import doctor  # re-export so tools.doctor() still works


# ---------------------------------------------------------------------------
# CLI-backed tools
# ---------------------------------------------------------------------------


async def status(workspace: str) -> dict:
    """Show status of all services in the Railway project."""
    return await _run_railway(workspace, ["status", "--json"])


async def logs(
    workspace: str,
    service: str,
    lines: int = 100,
    build: bool = False,
    filter: Optional[str] = None,
) -> dict:
    """Fetch recent logs from a Railway service."""
    args = ["logs", "--service", service, "--lines", str(lines)]
    if build:
        args.append("--build")
    if filter:
        args.extend(["--filter", filter])
    return await _run_railway(workspace, args, timeout=_LOGS_TIMEOUT)


async def deploy(workspace: str, service: str) -> dict:
    """Trigger a deploy for a Railway service (non-blocking, --detach)."""
    return await _run_railway(
        workspace, ["up", "--service", service, "--detach"], timeout=_DEPLOY_TIMEOUT
    )


async def variables(workspace: str, service: str) -> dict:
    """List environment variables for a Railway service."""
    return await _run_railway(workspace, ["variables", "--service", service, "--json"])


async def variable_set(workspace: str, service: str, key: str, value: str) -> dict:
    """Set an environment variable on a Railway service (triggers redeploy)."""
    return await _run_railway(
        workspace, ["variables", "--set", f"{key}={value}", "--service", service]
    )


async def services(workspace: str) -> dict:
    """List all services in the Railway project with deployment status."""
    return await _run_railway(workspace, ["service", "status"])


async def redeploy(workspace: str, service: str) -> dict:
    """Redeploy the latest deployment of a service (rebuilds from source)."""
    return await _run_railway(
        workspace, ["redeploy", "--service", service, "--yes", "--json"]
    )


async def restart(workspace: str, service: str) -> dict:
    """Restart the latest deployment of a service (no rebuild)."""
    return await _run_railway(
        workspace, ["restart", "--service", service, "--yes", "--json"]
    )


async def domain(
    workspace: str,
    service: str,
    domain: Optional[str] = None,
    port: Optional[int] = None,
) -> dict:
    """Generate a railway.app domain or add a custom domain to a service."""
    args = ["domain", "--service", service, "--json"]
    if domain:
        args.append(domain)
    if port is not None:
        args.extend(["--port", str(port)])
    return await _run_railway(workspace, args)


async def environment_create(workspace: str, name: str) -> dict:
    """Create a new environment in the Railway project."""
    return await _run_railway(workspace, ["environment", "new", name])


# ---------------------------------------------------------------------------
# GraphQL-backed tools
# ---------------------------------------------------------------------------


async def deployments(workspace: str, service: str, limit: int = 10) -> dict:
    """List recent deployments for a service with IDs, statuses, and timestamps."""
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
    deps = [edge["node"] for edge in edges]
    return {"deployments": deps, "count": len(deps)}


async def rollback(workspace: str, service: str, deployment_id: str) -> dict:
    """Roll back a service to a specific previous deployment."""
    token = _load_token(workspace)
    query = """
    mutation deploymentRollback($id: String!) {
      deploymentRollback(id: $id) { id status }
    }
    """
    return await _gql(token, query, {"id": deployment_id})


async def service_info(workspace: str, service: str) -> dict:
    """Get detailed configuration for a Railway service."""
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


async def http_logs(
    workspace: str,
    service: str,
    deployment_id: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Get HTTP request logs for a service — status codes, latency, paths."""
    token = _load_token(workspace)

    if not deployment_id:
        project = await _resolve_project(token)
        if "error" in project:
            return project
        project_id = project.get("projectId")
        service_id = await _resolve_service_id(token, project_id, service)
        if not service_id:
            return {"error": f"Service '{service}' not found in project"}

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
    log_entries = result.get("httpLogs", [])
    return {"logs": log_entries, "count": len(log_entries), "deployment_id": deployment_id}


async def unlink_repo(workspace: str, service: str) -> dict:
    """Disconnect a service from its linked GitHub repo."""
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


__all__ = [
    "status", "logs", "deploy", "variables", "variable_set", "services",
    "redeploy", "restart", "domain", "environment_create", "deployments",
    "rollback", "service_info", "http_logs", "unlink_repo", "doctor",
]
