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
