"""GraphQL backend — hits Railway's Backboard API directly."""

import httpx

BACKBOARD_URL = "https://backboard.railway.com/graphql/v2"


async def _gql(token: str, query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query against Railway's Backboard API.

    Uses Project-Access-Token header (not Bearer) for project-scoped tokens.
    """
    headers = {
        "Content-Type": "application/json",
        "Project-Access-Token": token,
    }
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(BACKBOARD_URL, headers=headers, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"Backboard API returned {exc.response.status_code}",
                "body": exc.response.text,
            }
        except httpx.RequestError as exc:
            return {"error": f"Request failed: {exc}"}

        data = resp.json()
        if "errors" in data:
            return {"error": "GraphQL error", "details": data["errors"]}
        return data.get("data", {})


async def _gql_bearer(token: str, query: str, variables: dict | None = None) -> dict:
    """Execute a GraphQL query using a user/account-level Bearer token.

    Account tokens use Authorization: Bearer (not Project-Access-Token).
    Required for account-level operations like creating projects.
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload: dict = {"query": query}
    if variables:
        payload["variables"] = variables

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(BACKBOARD_URL, headers=headers, json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            return {
                "error": f"Backboard API returned {exc.response.status_code}",
                "body": exc.response.text,
            }
        except httpx.RequestError as exc:
            return {"error": f"Request failed: {exc}"}

        data = resp.json()
        if "errors" in data:
            return {"error": "GraphQL error", "details": data["errors"]}
        return data.get("data", {})


def _load_user_token(account: str | None = None) -> str:
    """Load a Railway account token.

    Priority:
    1. Named account in ~/.railguey/accounts.json
    2. Default account in ~/.railguey/accounts.json
    3. RAILWAY_USER_TOKEN env var
    4. ~/.railway/config.json (CLI fallback)
    """
    from railguey.lib.accounts import get_account_token

    return get_account_token(account)


async def _resolve_project(token: str) -> dict:
    """Introspect the project token to get projectId and environmentId."""
    result = await _gql(token, "query { projectToken { projectId environmentId } }")
    if "error" in result:
        return result
    return result.get("projectToken", {})


async def _resolve_project_metadata(token: str) -> dict:
    """Introspect a project token AND fetch human-readable project metadata.

    Returns dict with: projectId, environmentId, projectName, teamName.
    Used by `railguey login` to show users what they're about to bind to
    before writing the token to disk. Failure to resolve metadata is
    non-fatal — a token that resolves projectToken but not project.name
    is still usable, just less informative in the confirmation step.
    """
    base = await _resolve_project(token)
    if "error" in base:
        return base
    project_id = base.get("projectId")
    if not project_id:
        return {"error": "projectToken returned no projectId"}

    query = """
    query project($id: String!) {
      project(id: $id) {
        id
        name
        team { name }
      }
    }
    """
    result = await _gql(token, query, {"id": project_id})
    project = result.get("project") if isinstance(result, dict) else None
    return {
        "projectId": project_id,
        "environmentId": base.get("environmentId"),
        "projectName": (project or {}).get("name"),
        "teamName": ((project or {}).get("team") or {}).get("name"),
    }


async def _resolve_service_id(
    token: str, project_id: str, service_name: str
) -> str | None:
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
