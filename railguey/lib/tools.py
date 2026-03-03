"""18 pure async tool functions — no framework decorators, no prefixes.

All tools use pure GraphQL (token-only, no CLI dependency).

Usage:
    from railguey.lib import tools
    result = await tools.status("/path/to/workspace")
"""

from typing import Optional

from railguey.lib.token import _load_token
from railguey.lib.graphql import _gql, _resolve_project, _resolve_service_id
from railguey.lib.doctor import doctor  # re-export so tools.doctor() still works


# ---------------------------------------------------------------------------
# GraphQL-backed tools (prefer these — no CLI dependency, token-only)
# ---------------------------------------------------------------------------


async def status(workspace: str) -> dict:
    """Show status of all services in the Railway project.

    Pure GraphQL — no CLI needed. Returns a compact summary: service names,
    latest deploy status, and domains. Typically ~1-2K instead of 50K+.
    """
    token = _load_token(workspace)
    project = await _resolve_project(token)
    if "error" in project:
        return project
    project_id = project.get("projectId")
    environment_id = project.get("environmentId")
    if not project_id or not environment_id:
        return {"error": "Could not resolve projectId/environmentId from token"}

    query = """
    query project($id: String!) {
      project(id: $id) {
        id
        name
        environments { edges { node { id name } } }
        services {
          edges {
            node {
              id
              name
              serviceInstances {
                edges {
                  node {
                    environmentId
                    startCommand
                    domains { serviceDomains { domain } customDomains { domain } }
                    latestDeployment { id status createdAt }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    result = await _gql(token, query, {"id": project_id})
    if "error" in result:
        return result

    proj = result.get("project", {})
    envs = {
        e["node"]["id"]: e["node"]["name"]
        for e in proj.get("environments", {}).get("edges", [])
    }

    services_out = []
    for svc_edge in proj.get("services", {}).get("edges", []):
        svc = svc_edge.get("node", {})
        for inst_edge in svc.get("serviceInstances", {}).get("edges", []):
            inst = inst_edge.get("node", {})
            env_id = inst.get("environmentId", "")
            if env_id != environment_id:
                continue  # only show the token's environment
            latest = inst.get("latestDeployment") or {}
            domains_data = inst.get("domains", {}) or {}
            all_domains = (
                [d.get("domain", "") for d in domains_data.get("serviceDomains", [])]
                + [d.get("domain", "") for d in domains_data.get("customDomains", [])]
            )
            services_out.append({
                "name": svc.get("name", "unknown"),
                "serviceId": svc.get("id", ""),
                "status": latest.get("status", "no deploys"),
                "deployedAt": latest.get("createdAt", ""),
                "domains": [d for d in all_domains if d],
            })

    return {
        "project": proj.get("name", "unknown"),
        "projectId": project_id,
        "environment": envs.get(environment_id, "unknown"),
        "services": services_out,
    }


async def logs(
    workspace: str,
    service: str,
    lines: int = 100,
    build: bool = False,
    filter: Optional[str] = None,
) -> dict:
    """Fetch recent logs from a Railway service.

    Pure GraphQL — no CLI needed. Uses deploymentLogs or buildLogs query.
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

    # Find latest deployment
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

    if build:
        query = """
        query buildLogs($deploymentId: String!, $limit: Int, $filter: String) {
          buildLogs(deploymentId: $deploymentId, limit: $limit, filter: $filter) {
            message timestamp severity
          }
        }
        """
        result_key = "buildLogs"
    else:
        query = """
        query deploymentLogs($deploymentId: String!, $limit: Int, $filter: String) {
          deploymentLogs(deploymentId: $deploymentId, limit: $limit, filter: $filter) {
            message timestamp severity
          }
        }
        """
        result_key = "deploymentLogs"

    gql_vars: dict = {"deploymentId": deployment_id, "limit": lines}
    if filter:
        gql_vars["filter"] = filter

    result = await _gql(token, query, gql_vars)
    if "error" in result:
        return result

    entries = result.get(result_key, [])
    return {
        "logs": entries,
        "count": len(entries),
        "service": service,
        "deploymentId": deployment_id,
    }


async def deploy(workspace: str, service: str) -> dict:
    """Trigger a deploy for a Railway service.

    Pure GraphQL — no CLI needed. Uses serviceInstanceRedeploy to rebuild
    from the existing linked source (GitHub commit or previous upload).
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
    mutation serviceInstanceRedeploy($environmentId: String!, $serviceId: String!) {
      serviceInstanceRedeploy(environmentId: $environmentId, serviceId: $serviceId)
    }
    """
    result = await _gql(token, query, {
        "environmentId": environment_id,
        "serviceId": service_id,
    })
    if "error" in result:
        return result
    return {"deployed": True, "service": service}


async def variables(workspace: str, service: str) -> dict:
    """List environment variables for a Railway service.

    Pure GraphQL — no CLI needed.
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
    query variables($environmentId: String!, $projectId: String!, $serviceId: String!) {
      variables(environmentId: $environmentId, projectId: $projectId, serviceId: $serviceId)
    }
    """
    result = await _gql(token, query, {
        "environmentId": environment_id,
        "projectId": project_id,
        "serviceId": service_id,
    })
    if "error" in result:
        return result
    return {"variables": result.get("variables", {}), "service": service}


async def variable_set(workspace: str, service: str, key: str, value: str) -> dict:
    """Set an environment variable on a Railway service (triggers redeploy).

    Pure GraphQL — no CLI needed.
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
    mutation variableUpsert($input: VariableUpsertInput!) {
      variableUpsert(input: $input)
    }
    """
    result = await _gql(token, query, {
        "input": {
            "environmentId": environment_id,
            "projectId": project_id,
            "serviceId": service_id,
            "name": key,
            "value": value,
        }
    })
    if "error" in result:
        return result
    return {"set": True, "key": key, "service": service}


async def services(workspace: str) -> dict:
    """List all services in the Railway project with deployment status.

    Pure GraphQL — no CLI needed. Returns service names and IDs.
    """
    token = _load_token(workspace)
    project = await _resolve_project(token)
    if "error" in project:
        return project
    project_id = project.get("projectId")
    if not project_id:
        return {"error": "Could not resolve projectId from token"}

    query = """
    query project($id: String!) {
      project(id: $id) {
        services { edges { node { id name } } }
      }
    }
    """
    result = await _gql(token, query, {"id": project_id})
    if "error" in result:
        return result
    edges = result.get("project", {}).get("services", {}).get("edges", [])
    svc_list = [{"name": e["node"]["name"], "id": e["node"]["id"]} for e in edges]
    return {"services": svc_list, "count": len(svc_list)}


async def redeploy(workspace: str, service: str) -> dict:
    """Redeploy the latest deployment of a service (rebuilds from source).

    Pure GraphQL — no CLI needed. Finds the latest deployment and triggers
    a redeploy via the deploymentRedeploy mutation.
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

    # Find latest deployment
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
    mutation deploymentRedeploy($id: String!) {
      deploymentRedeploy(id: $id) { id status }
    }
    """
    result = await _gql(token, query, {"id": deployment_id})
    if "error" in result:
        return result
    redeployed = result.get("deploymentRedeploy", {})
    return {
        "redeployed": True,
        "service": service,
        "deploymentId": redeployed.get("id", ""),
        "status": redeployed.get("status", ""),
    }


async def restart(workspace: str, service: str) -> dict:
    """Restart the latest deployment of a service (no rebuild).

    Pure GraphQL — no CLI needed. Finds the latest deployment and triggers
    a restart via the deploymentRestart mutation.
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

    # Find latest deployment
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
    mutation deploymentRestart($id: String!) {
      deploymentRestart(id: $id)
    }
    """
    result = await _gql(token, query, {"id": deployment_id})
    if "error" in result:
        return result
    return {
        "restarted": True,
        "service": service,
        "deploymentId": deployment_id,
    }


async def domain(
    workspace: str,
    service: str,
    domain: Optional[str] = None,
    port: Optional[int] = None,
) -> dict:
    """Generate a railway.app domain or add a custom domain to a service.

    Pure GraphQL — no CLI needed. If domain is provided, creates a custom
    domain. Otherwise generates a railway.app subdomain.
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

    if domain:
        # Custom domain
        query = """
        mutation customDomainCreate($input: CustomDomainCreateInput!) {
          customDomainCreate(input: $input) { id domain }
        }
        """
        input_vars: dict = {
            "domain": domain,
            "environmentId": environment_id,
            "projectId": project_id,
            "serviceId": service_id,
        }
        if port is not None:
            input_vars["targetPort"] = port
        result = await _gql(token, query, {"input": input_vars})
        if "error" in result:
            return result
        created = result.get("customDomainCreate", {})
    else:
        # Generate railway.app domain
        query = """
        mutation serviceDomainCreate($input: ServiceDomainCreateInput!) {
          serviceDomainCreate(input: $input) { id domain }
        }
        """
        input_vars = {
            "environmentId": environment_id,
            "serviceId": service_id,
        }
        if port is not None:
            input_vars["targetPort"] = port
        result = await _gql(token, query, {"input": input_vars})
        if "error" in result:
            return result
        created = result.get("serviceDomainCreate", {})

    return {
        "domain": created.get("domain", ""),
        "id": created.get("id", ""),
        "service": service,
        "custom": domain is not None,
    }


async def environment_create(workspace: str, name: str) -> dict:
    """Create a new environment in the Railway project.

    Pure GraphQL — no CLI needed.
    """
    token = _load_token(workspace)
    project = await _resolve_project(token)
    if "error" in project:
        return project
    project_id = project.get("projectId")
    if not project_id:
        return {"error": "Could not resolve projectId from token"}

    query = """
    mutation environmentCreate($input: EnvironmentCreateInput!) {
      environmentCreate(input: $input) { id name }
    }
    """
    result = await _gql(token, query, {
        "input": {"name": name, "projectId": project_id}
    })
    if "error" in result:
        return result
    env = result.get("environmentCreate", {})
    return {
        "created": True,
        "name": env.get("name", name),
        "environmentId": env.get("id", ""),
    }


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
    _ = service  # kept for MCP API consistency; rollback targets deployment_id directly
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
        if not project_id:
            return {"error": "Could not resolve projectId from token"}
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


async def deployment_logs(
    workspace: str,
    deployment_id: str,
    limit: int = 100,
    build: bool = False,
    filter: Optional[str] = None,
) -> dict:
    """Get logs for a specific deployment by ID.

    Use railguey_deployments to find deployment IDs, then this tool to
    inspect a specific one. Useful when multiple deployments (across
    environments or services) are interleaved.
    """
    token = _load_token(workspace)

    if build:
        query = """
        query buildLogs($deploymentId: String!, $limit: Int, $filter: String) {
          buildLogs(deploymentId: $deploymentId, limit: $limit, filter: $filter) {
            message timestamp severity
          }
        }
        """
        result_key = "buildLogs"
    else:
        query = """
        query deploymentLogs($deploymentId: String!, $limit: Int, $filter: String) {
          deploymentLogs(deploymentId: $deploymentId, limit: $limit, filter: $filter) {
            message timestamp severity
          }
        }
        """
        result_key = "deploymentLogs"

    gql_vars: dict = {"deploymentId": deployment_id, "limit": limit}
    if filter:
        gql_vars["filter"] = filter

    result = await _gql(token, query, gql_vars)
    if "error" in result:
        return result

    entries = result.get(result_key, [])
    return {
        "logs": entries,
        "count": len(entries),
        "deploymentId": deployment_id,
    }


async def unlink_repo(workspace: str, service: str) -> dict:
    """Disconnect a service from its linked GitHub repo."""
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
    "rollback", "service_info", "http_logs", "deployment_logs",
    "unlink_repo", "doctor",
]
