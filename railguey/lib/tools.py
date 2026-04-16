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
    _gql,
    _gql_bearer,
    _resolve_project,
    _resolve_service_id,
    _load_user_token,
)
from railguey.lib.doctor import doctor  # re-export


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
            all_domains = [
                d.get("domain", "") for d in domains_data.get("serviceDomains", [])
            ] + [d.get("domain", "") for d in domains_data.get("customDomains", [])]
            services_out.append(
                {
                    "name": svc.get("name", "unknown"),
                    "serviceId": svc.get("id", ""),
                    "status": latest.get("status", "no deploys"),
                    "deployedAt": latest.get("createdAt", ""),
                    "domains": [d for d in all_domains if d],
                }
            )

    return {
        "project": proj.get("name", "unknown"),
        "projectId": project_id,
        "environment": envs.get(environment_id, "unknown"),
        "services": services_out,
    }


async def pypi_status(packages: list[str] | None = None) -> dict:
    """Check PyPI publication status for Eidos packages.

    Compares local version (pyproject.toml), latest git tag, and PyPI
    published version. Reports: IN_SYNC, GIT_AHEAD, PUBLISH_FAILED, UNKNOWN.
    """
    import subprocess
    import tomllib

    from railguey.lib.orchestrate import _load_all_registries, _expand_home
    from railguey.lib.pypi import get_pypi_version

    # Collect pypi_package services from all registries
    pypi_services = []
    for reg in _load_all_registries():
        for svc in reg.get("services", []):
            if svc.get("type") == "pypi_package":
                if packages is None or svc["name"] in packages:
                    pypi_services.append(svc)

    if not pypi_services:
        return {"error": "No pypi_package services found in registry"}

    results = []
    for svc in pypi_services:
        ws = _expand_home(svc.get("workspace"))
        pypi_name = svc.get("deploy", {}).get("pypi_name", svc["name"])

        entry = {"name": svc["name"], "pypi_name": pypi_name}

        # Get local version from pyproject.toml
        if ws:
            pyproject_path = Path(ws) / "pyproject.toml"
            if pyproject_path.exists():
                try:
                    with open(pyproject_path, "rb") as f:
                        entry["local_version"] = tomllib.load(f)["project"]["version"]
                except Exception:
                    pass

        # Get latest git tag
        if ws and Path(ws).exists():
            try:
                result = subprocess.run(
                    ["git", "describe", "--tags", "--abbrev=0"],
                    cwd=ws,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    entry["latest_tag"] = result.stdout.strip()
            except Exception:
                pass

        # Get PyPI version
        pypi_info = await get_pypi_version(pypi_name)
        if "error" not in pypi_info:
            entry["pypi_version"] = pypi_info["version"]
        else:
            entry["pypi_version"] = None
            entry["pypi_error"] = pypi_info.get("error", "unknown")

        # Determine status
        local = entry.get("local_version")
        pypi_v = entry.get("pypi_version")
        tag = entry.get("latest_tag", "").lstrip("v")

        if not pypi_v:
            entry["status"] = "UNKNOWN"
        elif local == pypi_v and tag == pypi_v:
            entry["status"] = "IN_SYNC"
        elif local and local != pypi_v and tag == local:
            entry["status"] = "GIT_AHEAD"
        elif tag and tag != pypi_v and local == pypi_v:
            entry["status"] = "PUBLISH_FAILED"
        else:
            entry["status"] = "DRIFT"

        results.append(entry)

    return {"packages": results}


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
    dep_result = await _gql(
        token, dep_query, {"input": {"projectId": project_id, "serviceId": service_id}}
    )
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
    result = await _gql(
        token,
        query,
        {
            "environmentId": environment_id,
            "serviceId": service_id,
        },
    )
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
    result = await _gql(
        token,
        query,
        {
            "environmentId": environment_id,
            "projectId": project_id,
            "serviceId": service_id,
        },
    )
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
    result = await _gql(
        token,
        query,
        {
            "input": {
                "environmentId": environment_id,
                "projectId": project_id,
                "serviceId": service_id,
                "name": key,
                "value": value,
            }
        },
    )
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
    dep_result = await _gql(
        token, dep_query, {"input": {"projectId": project_id, "serviceId": service_id}}
    )
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
    dep_result = await _gql(
        token, dep_query, {"input": {"projectId": project_id, "serviceId": service_id}}
    )
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
    """Generate a railway.app domain, add a custom domain, or update an existing domain's port.

    Pure GraphQL — no CLI needed. If domain is provided, creates a custom
    domain. Otherwise generates a railway.app subdomain. If the domain already
    exists on the service and a port is provided, updates the target port.
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

    # Check if the domain already exists on this service
    existing = await _find_existing_domain(token, service_id, environment_id, domain)

    if existing:
        # Domain already exists
        if port is None:
            # No port change requested — just return existing info
            return {
                "domain": existing["domain"],
                "id": existing["id"],
                "service": service,
                "custom": existing["custom"],
                "existing": True,
            }
        # Update the target port on the existing domain
        return await _update_domain_port(
            existing,
            service_id,
            environment_id,
            service,
            port,
        )

    # Domain does not exist — create it
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


async def _find_existing_domain(
    token: str,
    service_id: str,
    environment_id: str,
    domain_str: Optional[str],
) -> Optional[dict]:
    """Check if a domain already exists on the service instance.

    Returns {"id": ..., "domain": ..., "custom": bool} if found, else None.
    """
    query = """
    query serviceInstance($serviceId: String!, $environmentId: String!) {
      serviceInstance(serviceId: $serviceId, environmentId: $environmentId) {
        domains {
          serviceDomains { id domain }
          customDomains { id domain }
        }
      }
    }
    """
    result = await _gql(
        token,
        query,
        {
            "serviceId": service_id,
            "environmentId": environment_id,
        },
    )
    if "error" in result:
        return None

    domains_data = (result.get("serviceInstance") or {}).get("domains") or {}

    # If a specific domain string was provided, look for an exact match
    if domain_str:
        for d in domains_data.get("customDomains", []):
            if d.get("domain") == domain_str:
                return {"id": d["id"], "domain": d["domain"], "custom": True}
        for d in domains_data.get("serviceDomains", []):
            if d.get("domain") == domain_str:
                return {"id": d["id"], "domain": d["domain"], "custom": False}
    else:
        # No domain string — check if any railway.app domain exists
        svc_domains = domains_data.get("serviceDomains", [])
        if svc_domains:
            d = svc_domains[0]
            return {"id": d["id"], "domain": d["domain"], "custom": False}

    return None


async def _update_domain_port(
    existing: dict,
    service_id: str,
    environment_id: str,
    service_name: str,
    port: int,
) -> dict:
    """Update the targetPort on an existing domain. Requires Bearer auth."""
    try:
        user_token = _load_user_token()
    except ValueError:
        return {
            "error": (
                "Updating a domain's targetPort requires a Bearer (account) token, "
                "but no account is registered. Project tokens cannot execute this mutation. "
                "Use railguey_account_add to register an account with access to this workspace."
            )
        }

    if existing["custom"]:
        query = """
        mutation customDomainUpdate($input: CustomDomainUpdateInput!) {
          customDomainUpdate(input: $input)
        }
        """
        input_vars = {
            "customDomainId": existing["id"],
            "serviceId": service_id,
            "environmentId": environment_id,
            "domain": existing["domain"],
            "targetPort": port,
        }
    else:
        query = """
        mutation serviceDomainUpdate($input: ServiceDomainUpdateInput!) {
          serviceDomainUpdate(input: $input)
        }
        """
        input_vars = {
            "serviceDomainId": existing["id"],
            "serviceId": service_id,
            "environmentId": environment_id,
            "domain": existing["domain"],
            "targetPort": port,
        }

    result = await _gql_bearer(user_token, query, {"input": input_vars})
    if "error" in result:
        return result

    return {
        "domain": existing["domain"],
        "id": existing["id"],
        "service": service_name,
        "custom": existing["custom"],
        "updated": True,
        "targetPort": port,
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
    result = await _gql(
        token, query, {"input": {"name": name, "projectId": project_id}}
    )
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
    result = await _gql(
        token,
        query,
        {
            "serviceId": service_id,
            "environmentId": environment_id,
        },
    )
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
        dep_result = await _gql(
            token,
            dep_query,
            {"input": {"projectId": project_id, "serviceId": service_id}},
        )
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
    return {
        "logs": log_entries,
        "count": len(log_entries),
        "deployment_id": deployment_id,
    }


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
    result = await _gql_bearer(
        user_token, create_query, {"input": {"name": name, "workspaceId": team_id}}
    )
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
    token_result = await _gql_bearer(
        user_token,
        token_query,
        {
            "input": {
                "projectId": project_id,
                "environmentId": env_id,
                "name": f"railguey-{name}",
            }
        },
    )
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
        "projectToken": project_token
        or "(failed to create — create manually in Railway dashboard)",
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
    result = await _gql(
        token, query, {"input": {"name": name, "projectId": project_id}}
    )
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
        {
            "id": e["node"]["id"],
            "name": e["node"]["name"],
            "updatedAt": e["node"].get("updatedAt", ""),
        }
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
    result = await _gql_bearer(
        user_token, query, {"id": project_id, "teamId": target_team_id}
    )
    if "error" in result:
        return result
    proj = result.get("projectTransferToTeam", {})
    return {
        "transferred": True,
        "projectId": proj.get("id", project_id),
        "targetTeamId": target_team_id,
    }


async def service_update(
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
    """Update service instance settings (healthcheck, commands, region, replicas, etc.).

    IMPORTANT: This mutation requires a Bearer (account) token, NOT a project token.
    The project token is used to resolve IDs, then an account token executes the mutation.

    Args:
        workspace: Absolute path to project directory with .env.local.
        service: Railway service name.
        healthcheck_path: Healthcheck endpoint path (e.g. "/health").
        start_command: Command to start the service.
        build_command: Command to build the service.
        root_directory: Root directory for the service source.
        region: Deployment region (e.g. "us-west1").
        num_replicas: Number of replicas.
        restart_policy_type: Restart policy type (e.g. "ON_FAILURE", "ALWAYS", "NEVER").
        restart_policy_max_retries: Max retries for restart policy.
    """
    # Build the input dict from non-None params
    field_map = {
        "healthcheck_path": "healthcheckPath",
        "start_command": "startCommand",
        "build_command": "buildCommand",
        "root_directory": "rootDirectory",
        "region": "region",
        "num_replicas": "numReplicas",
        "restart_policy_type": "restartPolicyType",
        "restart_policy_max_retries": "restartPolicyMaxRetries",
    }
    local_vars = {
        "healthcheck_path": healthcheck_path,
        "start_command": start_command,
        "build_command": build_command,
        "root_directory": root_directory,
        "region": region,
        "num_replicas": num_replicas,
        "restart_policy_type": restart_policy_type,
        "restart_policy_max_retries": restart_policy_max_retries,
    }
    gql_input = {}
    for snake, camel in field_map.items():
        val = local_vars[snake]
        if val is not None:
            gql_input[camel] = val

    if not gql_input:
        return {
            "error": "No fields to update. Provide at least one field (healthcheck_path, start_command, etc.)."
        }

    # Step 1: Use project token to resolve IDs
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

    # Step 2: Find an account token for Bearer auth (project tokens can't run this mutation)
    try:
        user_token = _load_user_token()
    except ValueError:
        return {
            "error": (
                "serviceInstanceUpdate requires a Bearer (account) token, but no account is registered. "
                "Project tokens cannot execute this mutation. "
                "Use railguey_account_add to register an account with access to this workspace."
            )
        }

    # Step 3: Execute the mutation with Bearer auth
    query = """
    mutation serviceInstanceUpdate($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
      serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input)
    }
    """
    result = await _gql_bearer(
        user_token,
        query,
        {
            "serviceId": service_id,
            "environmentId": environment_id,
            "input": gql_input,
        },
    )
    if "error" in result:
        return result

    return {
        "updated": True,
        "service": service,
        "serviceId": service_id,
        "fields": gql_input,
    }


async def volume_create(
    workspace: str,
    service: str,
    mount_path: str,
) -> dict:
    """Create a Railway volume and attach it to a service.

    Uses the project-scoped token from workspace/.env.local. Confirmed
    2026-04-15 that project tokens can execute volumeCreate — no account
    token required (unlike serviceInstanceUpdate). Railway names the
    volume `<service>-volume` automatically; default size is 50 GB.

    After creation the service redeploys automatically with the volume
    mounted at `mount_path`.
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
    mutation volumeCreate($input: VolumeCreateInput!) {
      volumeCreate(input: $input) { id name createdAt }
    }
    """
    result = await _gql(
        token,
        query,
        {
            "input": {
                "projectId": project_id,
                "serviceId": service_id,
                "environmentId": environment_id,
                "mountPath": mount_path,
            }
        },
    )
    if "error" in result:
        return result

    vol = result.get("volumeCreate", {})
    return {
        "created": True,
        "volumeId": vol.get("id", ""),
        "volumeName": vol.get("name", ""),
        "mountPath": mount_path,
        "service": service,
        "serviceId": service_id,
        "createdAt": vol.get("createdAt", ""),
    }


async def volumes(workspace: str) -> dict:
    """List all volumes in the Railway project with their mount state.

    Returns each volume with its volume instances (one per environment).
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
        volumes {
          edges {
            node {
              id
              name
              createdAt
              volumeInstances {
                edges {
                  node {
                    id
                    mountPath
                    sizeMB
                    state
                    environmentId
                    serviceId
                    region
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

    out = []
    edges = result.get("project", {}).get("volumes", {}).get("edges", [])
    for edge in edges:
        node = edge.get("node", {})
        instances = [
            inst_edge.get("node", {})
            for inst_edge in node.get("volumeInstances", {}).get("edges", [])
        ]
        out.append(
            {
                "id": node.get("id", ""),
                "name": node.get("name", ""),
                "createdAt": node.get("createdAt", ""),
                "instances": instances,
            }
        )
    return {"count": len(out), "volumes": out}


async def volume_delete(
    workspace: str,
    volume_id: str,
) -> dict:
    """Delete a Railway volume. Irreversible — all data on the volume is lost.

    Matches the existing project_delete pattern (no TOTP gate at the library
    layer; the destructive nature is documented in the tool docstring).
    """
    token = _load_token(workspace)
    query = """
    mutation volumeDelete($volumeId: String!) {
      volumeDelete(volumeId: $volumeId)
    }
    """
    result = await _gql(token, query, {"volumeId": volume_id})
    if "error" in result:
        return result
    return {"deleted": True, "volumeId": volume_id}


async def volume_resize(
    workspace: str,
    volume_instance_id: str,
    size_mb: int,
) -> dict:
    """Resize a volume instance to a new size (MB). Railway requires
    grow-only — you can increase but not shrink."""
    token = _load_token(workspace)
    project = await _resolve_project(token)
    if "error" in project:
        return project
    environment_id = project.get("environmentId")
    if not environment_id:
        return {"error": "Could not resolve environmentId from token"}

    query = """
    mutation volumeInstanceUpdate($volumeInstanceId: String!, $input: VolumeInstanceUpdateInput!) {
      volumeInstanceUpdate(volumeInstanceId: $volumeInstanceId, input: $input)
    }
    """
    result = await _gql(
        token,
        query,
        {
            "volumeInstanceId": volume_instance_id,
            "input": {"sizeMB": size_mb},
        },
    )
    if "error" in result:
        return result
    return {"resized": True, "volumeInstanceId": volume_instance_id, "sizeMB": size_mb}


__all__ = [
    "status",
    "logs",
    "deploy",
    "variables",
    "variable_set",
    "services",
    "redeploy",
    "restart",
    "domain",
    "environment_create",
    "deployments",
    "rollback",
    "service_info",
    "http_logs",
    "deployment_logs",
    "unlink_repo",
    "doctor",
    "project_create",
    "service_create",
    "list_workspaces",
    "list_projects",
    "project_delete",
    "project_transfer",
    "service_update",
    "volume_create",
    "volumes",
    "volume_delete",
    "volume_resize",
]
