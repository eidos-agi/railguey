"""18 pure async tool functions — no framework decorators, no prefixes.

All tools use pure GraphQL (token-only, no CLI dependency).

Usage:
    from railguey.lib import tools
    result = await tools.status("/path/to/workspace")
"""

from typing import Optional

from pathlib import Path

from railguey.lib.token import _load_token
from railguey.lib.graphql import (
    _gql, _gql_bearer, _resolve_project, _resolve_service_id, _load_user_token,
)
from railguey.lib.doctor import doctor, doctor_service_level, doctor_project_level  # re-export


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


async def list_workspaces(account: Optional[str] = None) -> dict:
    """Discover workspace ID(s) accessible by the account token.

    Works with both account-scoped and workspace-scoped tokens.
    For workspace-scoped tokens, discovers the workspace from projects.
    Auto-stores discovered workspace IDs in the account config.
    """
    from railguey.lib.accounts import set_workspace, set_default_workspace

    user_token = _load_user_token(account)

    # Try account-level query first (works with account-scoped tokens)
    query = """
    query { me { workspaces { id name } } }
    """
    result = await _gql_bearer(user_token, query)

    if "error" not in result:
        workspaces = result.get("me", {}).get("workspaces", [])
        ws_list = [{"id": w["id"], "name": w["name"]} for w in workspaces]
        # Auto-store in account config
        acct_name = account or "(default)"
        for w in ws_list:
            if account:
                set_workspace(account, w["name"], w["id"])
        if ws_list and account:
            set_default_workspace(account, ws_list[0]["id"])
        return {"account": acct_name, "workspaces": ws_list}

    # Fallback: workspace-scoped token — discover from projects
    proj_query = """
    query { projects { edges { node { workspaceId workspace { id name } } } } }
    """
    proj_result = await _gql_bearer(user_token, proj_query)
    if "error" in proj_result:
        return proj_result

    edges = proj_result.get("projects", {}).get("edges", [])
    seen = {}
    for e in edges:
        node = e.get("node", {})
        ws_id = node.get("workspaceId", "")
        ws = node.get("workspace")
        ws_name = ws.get("name", "") if ws else ""
        if ws_id and ws_id not in seen:
            seen[ws_id] = ws_name or ws_id

    ws_list = [{"id": k, "name": v} for k, v in seen.items()]

    # Auto-store in account config
    if account:
        for w in ws_list:
            set_workspace(account, w["name"], w["id"])
        if ws_list:
            set_default_workspace(account, ws_list[0]["id"])

    return {"account": account or "(default)", "workspaces": ws_list}


async def project_create(
    name: str,
    team_id: str,
    workspace: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Create a new Railway project in a specific team/workspace.

    REQUIRES team_id — will never create a project in the default/personal
    workspace by accident. Use list_workspaces() to find available teams.

    Args:
        name: Project name.
        team_id: Railway workspace/team ID (REQUIRED). Use list_workspaces() to find it.
        workspace: Local directory path. If provided, writes RAILWAY_TOKEN to .env.local.
        account: Named account from ~/.railguey/accounts.json. Uses default if not set.

    Returns the projectId, default environmentId, and a project token.
    """
    if not team_id:
        return {
            "error": "team_id is required. Use railguey_workspaces to list available "
                     "teams, then pass the team ID. Railguey never creates projects "
                     "without an explicit team to prevent accidental personal-account deploys."
        }

    user_token = _load_user_token(account)

    # Step 1: Create the project in the specified team
    create_query = """
    mutation projectCreate($input: ProjectCreateInput!) {
      projectCreate(input: $input) {
        id
        name
        environments { edges { node { id name } } }
      }
    }
    """
    result = await _gql_bearer(user_token, create_query, {
        "input": {"name": name, "workspaceId": team_id}
    })
    if "error" in result:
        return result

    project = result.get("projectCreate", {})
    project_id = project.get("id", "")
    envs = project.get("environments", {}).get("edges", [])
    env_id = envs[0]["node"]["id"] if envs else ""
    env_name = envs[0]["node"]["name"] if envs else "production"

    if not project_id:
        return {"error": "Project created but no ID returned", "raw": result}

    # Step 2: Create a project token for ongoing access
    token_query = """
    mutation projectTokenCreate($input: ProjectTokenCreateInput!) {
      projectTokenCreate(input: $input)
    }
    """
    token_result = await _gql_bearer(user_token, token_query, {
        "input": {
            "projectId": project_id,
            "environmentId": env_id,
            "name": f"railguey-{name}",
        }
    })
    project_token = ""
    if "error" not in token_result:
        project_token = token_result.get("projectTokenCreate", "")

    # Step 3: Write .env.local if workspace provided and token obtained
    env_local_written = False
    if workspace and project_token:
        ws = Path(workspace).expanduser().resolve()
        env_local = ws / ".env.local"
        env_local.write_text(f"RAILWAY_TOKEN={project_token}\n")
        env_local_written = True

    return {
        "created": True,
        "projectId": project_id,
        "projectName": project.get("name", name),
        "teamId": team_id,
        "environmentId": env_id,
        "environmentName": env_name,
        "projectToken": project_token or "(failed to create — create manually in Railway dashboard)",
        "envLocalWritten": env_local_written,
        "workspace": workspace or "(not specified)",
    }


async def service_create(
    workspace: str,
    name: str,
) -> dict:
    """Create a new empty service in a Railway project.

    Uses the project-scoped token from workspace/.env.local.
    After creation, the service exists but has no deployments —
    use railguey_deploy or link a GitHub repo to trigger the first build.
    """
    token = _load_token(workspace)
    project = await _resolve_project(token)
    if "error" in project:
        return project
    project_id = project.get("projectId")
    if not project_id:
        return {"error": "Could not resolve projectId from token"}

    query = """
    mutation serviceCreate($input: ServiceCreateInput!) {
      serviceCreate(input: $input) { id name }
    }
    """
    result = await _gql(token, query, {
        "input": {"name": name, "projectId": project_id}
    })
    if "error" in result:
        return result

    svc = result.get("serviceCreate", {})
    return {
        "created": True,
        "serviceId": svc.get("id", ""),
        "serviceName": svc.get("name", name),
        "projectId": project_id,
    }


async def list_projects(
    team_id: str,
    account: Optional[str] = None,
) -> dict:
    """List all projects in a workspace/team.

    Args:
        team_id: Railway workspace/team ID.
        account: Named account (uses default if not set).
    """
    user_token = _load_user_token(account)
    query = """
    query workspace($id: String!) {
      workspace(id: $id) {
        name
        projects { edges { node { id name updatedAt } } }
      }
    }
    """
    result = await _gql_bearer(user_token, query, {"id": team_id})
    if "error" in result:
        return result

    ws = result.get("workspace", {})
    edges = ws.get("projects", {}).get("edges", [])
    projects = [
        {"id": e["node"]["id"], "name": e["node"]["name"], "updatedAt": e["node"].get("updatedAt", "")}
        for e in edges
    ]
    return {"workspace": ws.get("name", ""), "teamId": team_id, "projects": projects}


async def project_delete(
    project_id: str,
    account: Optional[str] = None,
) -> dict:
    """Delete a Railway project. Irreversible.

    Args:
        project_id: Railway project ID to delete.
        account: Named account (uses default if not set).
    """
    user_token = _load_user_token(account)
    query = """
    mutation projectDelete($id: String!) {
      projectDelete(id: $id)
    }
    """
    result = await _gql_bearer(user_token, query, {"id": project_id})
    if "error" in result:
        return result
    return {"deleted": True, "projectId": project_id}


async def project_transfer(
    project_id: str,
    target_team_id: str,
    account: Optional[str] = None,
) -> dict:
    """Transfer a project to a different team/workspace.

    Args:
        project_id: Railway project ID to transfer.
        target_team_id: Destination workspace/team ID.
        account: Named account (uses default if not set).
    """
    user_token = _load_user_token(account)
    query = """
    mutation projectTransferToTeam($id: String!, $teamId: String!) {
      projectTransferToTeam(id: $id, teamId: $teamId) { id name }
    }
    """
    result = await _gql_bearer(user_token, query, {"id": project_id, "teamId": target_team_id})
    if "error" in result:
        return result
    proj = result.get("projectTransferToTeam", {})
    return {"transferred": True, "projectId": proj.get("id", project_id), "targetTeamId": target_team_id}


__all__ = [
    "status", "logs", "deploy", "variables", "variable_set", "services",
    "redeploy", "restart", "domain", "environment_create", "deployments",
    "rollback", "service_info", "http_logs", "deployment_logs",
    "unlink_repo", "doctor", "project_create", "service_create",
    "list_workspaces", "list_projects", "project_delete", "project_transfer",
]
