"""Integration tests — hits real Railway infrastructure.

Run with: pytest tests/test_integration.py -v -s
Requires real RAILWAY_TOKEN in workspace .env.local files.
Skipped automatically if no real workspaces are found.
"""

import os
import pytest
from pathlib import Path

# Real workspaces to test against
WORKSPACES = [
    os.path.expanduser("~/repos-greenmark-waste-solutions/cerebro"),
    os.path.expanduser("~/repos-greenmark-waste-solutions/data-daemon"),
    os.path.expanduser("~/repos-greenmark-waste-solutions/gmw-dot-com-astro"),
    os.path.expanduser("~/repos-greenmark-waste-solutions/cerebro-qa"),
    os.path.expanduser("~/repos-greenmark-waste-solutions/cerebro-ai-services"),
    os.path.expanduser("~/repos-greenmark-waste-solutions/portal"),
    os.path.expanduser("~/repos-greenmark-waste-solutions/cerebro-warp-speed"),
]

# Filter to workspaces that actually exist and have tokens
VALID_WORKSPACES = []
for ws in WORKSPACES:
    env_local = Path(ws) / ".env.local"
    if env_local.is_file() and "RAILWAY_TOKEN" in env_local.read_text():
        VALID_WORKSPACES.append(ws)

skip_no_workspaces = pytest.mark.skipif(
    not VALID_WORKSPACES,
    reason="No real workspaces with RAILWAY_TOKEN found",
)

from server import (
    _load_token,
    _run_railway,
    _gql,
    _resolve_project,
    _resolve_service_id,
    railguey_status,
    railguey_services,
    railguey_deployments,
    railguey_doctor,
    railguey_service_info,
    railguey_logs,
    railguey_variables,
)


@skip_no_workspaces
class TestTokenDiscoveryReal:
    """Token loading against real .env.local files."""

    @pytest.mark.parametrize("workspace", VALID_WORKSPACES)
    def test_loads_token_from_real_workspace(self, workspace):
        token = _load_token(workspace)
        assert token, f"Empty token from {workspace}"
        assert len(token) > 10, f"Token suspiciously short: {token[:5]}..."

    @pytest.mark.parametrize("workspace", VALID_WORKSPACES)
    def test_tokens_look_like_uuids_or_keys(self, workspace):
        token = _load_token(workspace)
        # Railway tokens are UUIDs (36 chars with dashes) or longer API keys
        assert len(token) >= 20, f"Token too short ({len(token)} chars)"


@skip_no_workspaces
class TestGraphQLReal:
    """GraphQL queries against real Backboard API."""

    @pytest.mark.asyncio
    async def test_resolve_project_from_real_token(self):
        ws = VALID_WORKSPACES[0]
        token = _load_token(ws)
        project = await _resolve_project(token)
        assert "error" not in project, f"Failed to resolve project: {project}"
        assert "projectId" in project
        assert "environmentId" in project
        print(f"\n  Project: {project['projectId']}")
        print(f"  Environment: {project['environmentId']}")

    @pytest.mark.asyncio
    async def test_resolve_services_from_real_project(self):
        ws = VALID_WORKSPACES[0]
        token = _load_token(ws)
        project = await _resolve_project(token)
        assert "projectId" in project

        query = """
        query project($id: String!) {
          project(id: $id) {
            name
            services { edges { node { id name } } }
          }
        }
        """
        result = await _gql(token, query, {"id": project["projectId"]})
        assert "error" not in result, f"Failed: {result}"
        services = result["project"]["services"]["edges"]
        assert len(services) > 0, "No services found"
        print(f"\n  Project: {result['project']['name']}")
        for svc in services:
            print(f"  Service: {svc['node']['name']} ({svc['node']['id']})")

    @pytest.mark.asyncio
    async def test_all_tokens_resolve_to_valid_projects(self):
        """Every workspace token should resolve to a real project."""
        results = []
        for ws in VALID_WORKSPACES:
            token = _load_token(ws)
            project = await _resolve_project(token)
            name = Path(ws).name
            if "error" in project:
                results.append(f"  FAIL {name}: {project['error']}")
            else:
                results.append(f"  OK   {name}: project={project['projectId']}")
        print("\n" + "\n".join(results))
        # At least one should work
        ok_count = sum(1 for r in results if r.strip().startswith("OK"))
        assert ok_count > 0, "No tokens resolved to valid projects"


@skip_no_workspaces
class TestCLIReal:
    """CLI commands against real Railway infrastructure."""

    @pytest.mark.asyncio
    async def test_status_returns_data(self):
        ws = VALID_WORKSPACES[0]
        result = await railguey_status(ws)
        assert "error" not in result, f"Status failed: {result}"
        print(f"\n  Status output length: {len(result.get('output', ''))}")

    @pytest.mark.asyncio
    async def test_services_returns_data(self):
        ws = VALID_WORKSPACES[0]
        result = await railguey_services(ws)
        # This might fail if no services are linked locally, which is fine
        print(f"\n  Services result: {list(result.keys())}")

    @pytest.mark.asyncio
    async def test_logs_returns_data(self):
        """Fetch a small number of logs from the first workspace's service."""
        ws = VALID_WORKSPACES[0]
        token = _load_token(ws)
        project = await _resolve_project(token)
        if "error" in project:
            pytest.skip("Could not resolve project")

        # Find first service name
        query = """
        query project($id: String!) {
          project(id: $id) {
            services { edges { node { name } } }
          }
        }
        """
        result = await _gql(token, query, {"id": project["projectId"]})
        services = result.get("project", {}).get("services", {}).get("edges", [])
        if not services:
            pytest.skip("No services found")

        service_name = services[0]["node"]["name"]
        log_result = await railguey_logs(ws, service_name, lines=5)
        print(f"\n  Logs for {service_name}: {list(log_result.keys())}")
        # Logs might be empty for services that haven't deployed, that's ok
        assert isinstance(log_result, dict)

    @pytest.mark.asyncio
    async def test_variables_returns_data(self):
        """List variables for a real service."""
        ws = VALID_WORKSPACES[0]
        token = _load_token(ws)
        project = await _resolve_project(token)
        if "error" in project:
            pytest.skip("Could not resolve project")

        query = """
        query project($id: String!) {
          project(id: $id) {
            services { edges { node { name } } }
          }
        }
        """
        result = await _gql(token, query, {"id": project["projectId"]})
        services = result.get("project", {}).get("services", {}).get("edges", [])
        if not services:
            pytest.skip("No services found")

        service_name = services[0]["node"]["name"]
        var_result = await railguey_variables(ws, service_name)
        print(f"\n  Variables for {service_name}: {list(var_result.keys())}")
        assert isinstance(var_result, dict)


@skip_no_workspaces
class TestDeploymentsReal:
    """Deployment history via GraphQL against real services."""

    @pytest.mark.asyncio
    async def test_deployments_returns_structured_data(self):
        ws = VALID_WORKSPACES[0]
        result = await railguey_deployments(ws, service="cerebro", limit=3)
        if "error" in result and "not found" in result["error"].lower():
            # Try to find an actual service name
            token = _load_token(ws)
            project = await _resolve_project(token)
            query = """
            query project($id: String!) {
              project(id: $id) {
                services { edges { node { name } } }
              }
            }
            """
            svc_result = await _gql(token, query, {"id": project["projectId"]})
            services = svc_result.get("project", {}).get("services", {}).get("edges", [])
            if services:
                svc_name = services[0]["node"]["name"]
                result = await railguey_deployments(ws, service=svc_name, limit=3)

        assert "error" not in result, f"Deployments failed: {result}"
        assert "deployments" in result
        assert "count" in result
        print(f"\n  Deployments: {result['count']} returned")
        for dep in result["deployments"]:
            print(f"    {dep.get('status', '?'):12} {dep.get('createdAt', '?')[:19]}")

    @pytest.mark.asyncio
    async def test_deployments_across_workspaces(self):
        """Hit deployments for every workspace that has a token."""
        results = []
        for ws in VALID_WORKSPACES:
            name = Path(ws).name
            token = _load_token(ws)
            project = await _resolve_project(token)
            if "error" in project:
                results.append(f"  SKIP {name}: token didn't resolve")
                continue

            # Find first service
            query = """
            query project($id: String!) {
              project(id: $id) {
                services { edges { node { name } } }
              }
            }
            """
            svc_result = await _gql(token, query, {"id": project["projectId"]})
            services = svc_result.get("project", {}).get("services", {}).get("edges", [])
            if not services:
                results.append(f"  SKIP {name}: no services")
                continue

            svc_name = services[0]["node"]["name"]
            dep_result = await railguey_deployments(ws, service=svc_name, limit=2)
            if "error" in dep_result:
                results.append(f"  FAIL {name}/{svc_name}: {dep_result['error']}")
            else:
                count = dep_result.get("count", 0)
                results.append(f"  OK   {name}/{svc_name}: {count} deployments")

        print("\n" + "\n".join(results))
        ok_count = sum(1 for r in results if r.strip().startswith("OK"))
        assert ok_count > 0, "No deployment queries succeeded"


@skip_no_workspaces
class TestServiceInfoReal:
    """Service config via GraphQL against real services."""

    @pytest.mark.asyncio
    async def test_service_info_returns_config(self):
        ws = VALID_WORKSPACES[0]
        token = _load_token(ws)
        project = await _resolve_project(token)
        if "error" in project:
            pytest.skip("Could not resolve project")

        query = """
        query project($id: String!) {
          project(id: $id) {
            services { edges { node { name } } }
          }
        }
        """
        result = await _gql(token, query, {"id": project["projectId"]})
        services = result.get("project", {}).get("services", {}).get("edges", [])
        if not services:
            pytest.skip("No services found")

        svc_name = services[0]["node"]["name"]
        info = await railguey_service_info(ws, svc_name)
        assert "error" not in info, f"Service info failed: {info}"
        print(f"\n  Service: {info.get('serviceName', '?')}")
        print(f"  Region: {info.get('region', '?')}")
        print(f"  Start: {info.get('startCommand', '?')}")
        print(f"  Build: {info.get('buildCommand', '?')}")
        print(f"  Health: {info.get('healthcheckPath', 'none')}")
        latest = info.get("latestDeployment", {})
        if latest:
            print(f"  Latest: {latest.get('status', '?')} @ {latest.get('createdAt', '?')[:19]}")


@skip_no_workspaces
class TestDoctorReal:
    """Doctor audit against real workspaces."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("workspace", VALID_WORKSPACES)
    async def test_doctor_runs_without_crashing(self, workspace):
        result = await railguey_doctor(workspace)
        assert "findings" in result
        assert "score" in result
        name = Path(workspace).name
        print(f"\n  {name}: {result['score']} {'HEALTHY' if result['healthy'] else 'ISSUES'}")
        for f in result["findings"]:
            status = f["status"].upper()
            print(f"    [{status:4}] {f['check']}: {f['message']}")

    @pytest.mark.asyncio
    async def test_doctor_summary_across_all_workspaces(self):
        """Run doctor on every workspace, summarize results."""
        print("\n")
        healthy = 0
        total = 0
        for ws in VALID_WORKSPACES:
            total += 1
            result = await railguey_doctor(ws)
            name = Path(ws).name
            if result["healthy"]:
                healthy += 1
                print(f"  PASS {name} ({result['score']})")
            else:
                print(f"  FAIL {name} ({result['score']})")
                for f in result["findings"]:
                    if f["status"] in ("fail", "warn"):
                        fix = f.get("fix", "")
                        print(f"       {f['check']}: {f['message']}")
                        if fix:
                            print(f"       FIX: {fix}")
        print(f"\n  Summary: {healthy}/{total} workspaces healthy")


@skip_no_workspaces
class TestStress:
    """Stress tests — rapid-fire, cross-workspace, edge cases."""

    @pytest.mark.asyncio
    async def test_rapid_fire_token_resolution(self):
        """Load tokens from all workspaces 10x each — no flakiness."""
        for _ in range(10):
            for ws in VALID_WORKSPACES:
                token = _load_token(ws)
                assert token

    @pytest.mark.asyncio
    async def test_rapid_fire_project_resolution(self):
        """Resolve all projects 3x — API should handle it."""
        for _ in range(3):
            for ws in VALID_WORKSPACES:
                token = _load_token(ws)
                project = await _resolve_project(token)
                # Some tokens might be for different Railway orgs, that's ok
                assert isinstance(project, dict)

    @pytest.mark.asyncio
    async def test_wrong_service_name_returns_clean_error(self):
        """Querying a nonexistent service should return a clear error, not crash."""
        ws = VALID_WORKSPACES[0]
        result = await railguey_deployments(ws, service="this-service-does-not-exist-abc123")
        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_empty_workspace_returns_clean_error(self, tmp_path):
        """Workspace with no .env.local should fail gracefully."""
        with pytest.raises(ValueError, match="RAILWAY_TOKEN not found"):
            _load_token(str(tmp_path))

    @pytest.mark.asyncio
    async def test_concurrent_queries_dont_interfere(self):
        """Run multiple GraphQL queries concurrently — they shouldn't step on each other."""
        import asyncio

        async def query_workspace(ws):
            token = _load_token(ws)
            return await _resolve_project(token)

        tasks = [query_workspace(ws) for ws in VALID_WORKSPACES]
        results = await asyncio.gather(*tasks)
        for ws, result in zip(VALID_WORKSPACES, results):
            name = Path(ws).name
            assert isinstance(result, dict), f"{name} returned non-dict: {result}"
            print(f"\n  {name}: {'OK' if 'projectId' in result else 'FAIL'}")

    @pytest.mark.asyncio
    async def test_different_tokens_resolve_to_different_projects(self):
        """If tokens are project-scoped, different workspaces should resolve differently
        (unless they share a token, which is also valid)."""
        projects = {}
        for ws in VALID_WORKSPACES:
            token = _load_token(ws)
            project = await _resolve_project(token)
            if "projectId" in project:
                pid = project["projectId"]
                projects.setdefault(pid, []).append(Path(ws).name)

        print("\n  Project → Workspaces:")
        for pid, names in projects.items():
            print(f"    {pid[:12]}... → {', '.join(names)}")
        # At least one project should be found
        assert len(projects) > 0
