"""Tests for railguey.lib.tools — all 18 tool functions.

Every tool is pure GraphQL now. Tests mock _resolve_project, _resolve_service_id,
and _gql at the tools module level (where they're imported).
"""

from unittest.mock import AsyncMock, patch

import pytest

from railguey.lib.tools import (
    status,
    logs,
    deploy,
    variables,
    variable_set,
    services,
    redeploy,
    restart,
    domain,
    environment_create,
    deployments,
    rollback,
    service_info,
    http_logs,
    deployment_logs,
    unlink_repo,
    service_update,
    upload_source,
    buckets,
    bucket_create,
    bucket_info,
    bucket_credentials,
    bucket_rename,
    bucket_delete,
)

# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

PROJECT = {"projectId": "proj-abc", "environmentId": "env-xyz"}

DEPLOYMENT_EDGES = {"deployments": {"edges": [{"node": {"id": "dep-001"}}]}}

DEPLOYMENT_EDGES_EMPTY = {"deployments": {"edges": []}}


def _patch_project(return_value=None):
    return patch(
        "railguey.lib.tools._resolve_project",
        new_callable=AsyncMock,
        return_value=return_value or PROJECT,
    )


def _patch_service_id(return_value: str | None = "svc-111"):
    return patch(
        "railguey.lib.tools._resolve_service_id",
        new_callable=AsyncMock,
        return_value=return_value,
    )


def _patch_gql(*responses):
    """Patch _gql with sequential responses (side_effect) or a single one."""
    if len(responses) == 1:
        return patch(
            "railguey.lib.tools._gql",
            new_callable=AsyncMock,
            return_value=responses[0],
        )
    return patch(
        "railguey.lib.tools._gql",
        new_callable=AsyncMock,
        side_effect=list(responses),
    )


# ===================================================================
# status
# ===================================================================


class TestStatus:
    async def test_happy_path(self, workspace_with_token):
        gql_response = {
            "project": {
                "name": "my-project",
                "environments": {
                    "edges": [{"node": {"id": "env-xyz", "name": "production"}}]
                },
                "services": {
                    "edges": [
                        {
                            "node": {
                                "id": "svc-111",
                                "name": "web",
                                "serviceInstances": {
                                    "edges": [
                                        {
                                            "node": {
                                                "environmentId": "env-xyz",
                                                "startCommand": "node start",
                                                "domains": {
                                                    "serviceDomains": [
                                                        {"domain": "web.up.railway.app"}
                                                    ],
                                                    "customDomains": [],
                                                },
                                                "latestDeployment": {
                                                    "id": "dep-1",
                                                    "status": "SUCCESS",
                                                    "createdAt": "2026-01-01T00:00:00Z",
                                                },
                                            }
                                        }
                                    ]
                                },
                            }
                        }
                    ]
                },
            }
        }
        with _patch_project(), _patch_gql(gql_response):
            result = await status(str(workspace_with_token))
        assert result["project"] == "my-project"
        assert result["projectId"] == "proj-abc"
        assert result["environment"] == "production"
        assert len(result["services"]) == 1
        svc = result["services"][0]
        assert svc["name"] == "web"
        assert svc["status"] == "SUCCESS"
        assert "web.up.railway.app" in svc["domains"]

    async def test_filters_other_environments(self, workspace_with_token):
        """Services in other environments are excluded."""
        gql_response = {
            "project": {
                "name": "proj",
                "environments": {"edges": []},
                "services": {
                    "edges": [
                        {
                            "node": {
                                "id": "svc-1",
                                "name": "web",
                                "serviceInstances": {
                                    "edges": [
                                        {
                                            "node": {
                                                "environmentId": "env-OTHER",
                                                "domains": {},
                                                "latestDeployment": None,
                                            }
                                        },
                                    ]
                                },
                            }
                        }
                    ]
                },
            }
        }
        with _patch_project(), _patch_gql(gql_response):
            result = await status(str(workspace_with_token))
        assert result["services"] == []

    async def test_project_error_passthrough(self, workspace_with_token):
        with _patch_project({"error": "bad token"}):
            result = await status(str(workspace_with_token))
        assert result == {"error": "bad token"}

    async def test_gql_error_passthrough(self, workspace_with_token):
        with _patch_project(), _patch_gql({"error": "timeout"}):
            result = await status(str(workspace_with_token))
        assert result["error"] == "timeout"

    async def test_no_deploys(self, workspace_with_token):
        """Service with no deployments shows 'no deploys'."""
        gql_response = {
            "project": {
                "name": "proj",
                "environments": {
                    "edges": [{"node": {"id": "env-xyz", "name": "prod"}}]
                },
                "services": {
                    "edges": [
                        {
                            "node": {
                                "id": "svc-1",
                                "name": "web",
                                "serviceInstances": {
                                    "edges": [
                                        {
                                            "node": {
                                                "environmentId": "env-xyz",
                                                "domains": {},
                                                "latestDeployment": None,
                                            }
                                        },
                                    ]
                                },
                            }
                        }
                    ]
                },
            }
        }
        with _patch_project(), _patch_gql(gql_response):
            result = await status(str(workspace_with_token))
        assert result["services"][0]["status"] == "no deploys"


# ===================================================================
# logs
# ===================================================================


class TestLogs:
    async def test_deploy_logs(self, workspace_with_token):
        log_entries = {
            "deploymentLogs": [
                {
                    "message": "Starting server",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "severity": "info",
                },
                {
                    "message": "Listening on :3000",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "severity": "info",
                },
            ]
        }
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(DEPLOYMENT_EDGES, log_entries),
        ):
            result = await logs(str(workspace_with_token), "web")
        assert result["count"] == 2
        assert result["service"] == "web"
        assert result["deploymentId"] == "dep-001"
        assert result["logs"][0]["message"] == "Starting server"

    async def test_build_logs(self, workspace_with_token):
        log_entries = {
            "buildLogs": [
                {
                    "message": "Building...",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "severity": "info",
                },
            ]
        }
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(DEPLOYMENT_EDGES, log_entries),
        ):
            result = await logs(str(workspace_with_token), "web", build=True)
        assert result["count"] == 1
        assert result["logs"][0]["message"] == "Building..."

    async def test_with_filter(self, workspace_with_token):
        log_entries = {"deploymentLogs": []}
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(DEPLOYMENT_EDGES, log_entries) as mock_gql,
        ):
            await logs(str(workspace_with_token), "web", filter="ERROR")
        # Second call should include filter in variables
        _, call_kwargs = mock_gql.call_args_list[1]
        assert "ERROR" in str(call_kwargs) or "ERROR" in str(mock_gql.call_args_list[1])

    async def test_with_lines(self, workspace_with_token):
        log_entries = {"deploymentLogs": []}
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(DEPLOYMENT_EDGES, log_entries) as mock_gql,
        ):
            await logs(str(workspace_with_token), "web", lines=50)
        # Second _gql call should pass limit=50
        args = mock_gql.call_args_list[1]
        gql_vars = args[0][2]  # third positional arg is variables dict
        assert gql_vars["limit"] == 50

    async def test_no_deployments(self, workspace_with_token):
        with _patch_project(), _patch_service_id(), _patch_gql(DEPLOYMENT_EDGES_EMPTY):
            result = await logs(str(workspace_with_token), "web")
        assert "error" in result
        assert "No deployments" in result["error"]

    async def test_service_not_found(self, workspace_with_token):
        with _patch_project(), _patch_service_id(None):
            result = await logs(str(workspace_with_token), "ghost")
        assert "error" in result
        assert "ghost" in result["error"]


# ===================================================================
# deploy
# ===================================================================


class TestDeploy:
    async def test_happy_path(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql({"serviceInstanceRedeploy": True}),
        ):
            result = await deploy(str(workspace_with_token), "web")
        assert result["deployed"] is True
        assert result["service"] == "web"

    async def test_service_not_found(self, workspace_with_token):
        with _patch_project(), _patch_service_id(None):
            result = await deploy(str(workspace_with_token), "ghost")
        assert "error" in result

    async def test_gql_error(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql({"error": "mutation failed"}),
        ):
            result = await deploy(str(workspace_with_token), "web")
        assert result["error"] == "mutation failed"


# ===================================================================
# variables
# ===================================================================


class TestVariables:
    async def test_happy_path(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(
                {
                    "variables": {
                        "DATABASE_URL": "postgres://...",
                        "NODE_ENV": "production",
                    }
                }
            ),
        ):
            result = await variables(str(workspace_with_token), "web")
        assert result["service"] == "web"
        assert "DATABASE_URL" in result["variables"]

    async def test_service_not_found(self, workspace_with_token):
        with _patch_project(), _patch_service_id(None):
            result = await variables(str(workspace_with_token), "ghost")
        assert "error" in result


# ===================================================================
# variable_set
# ===================================================================


class TestVariableSet:
    async def test_happy_path(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql({"variableUpsert": True}),
        ):
            result = await variable_set(str(workspace_with_token), "web", "FOO", "bar")
        assert result["set"] is True
        assert result["key"] == "FOO"
        assert result["service"] == "web"

    async def test_gql_error(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql({"error": "unauthorized"}),
        ):
            result = await variable_set(str(workspace_with_token), "web", "FOO", "bar")
        assert result["error"] == "unauthorized"


# ===================================================================
# services
# ===================================================================


class TestServices:
    async def test_happy_path(self, workspace_with_token):
        gql_response = {
            "project": {
                "services": {
                    "edges": [
                        {"node": {"id": "svc-1", "name": "web"}},
                        {"node": {"id": "svc-2", "name": "worker"}},
                    ]
                }
            }
        }
        with _patch_project(), _patch_gql(gql_response):
            result = await services(str(workspace_with_token))
        assert result["count"] == 2
        assert result["services"][0]["name"] == "web"
        assert result["services"][1]["id"] == "svc-2"

    async def test_empty_project(self, workspace_with_token):
        with _patch_project(), _patch_gql({"project": {"services": {"edges": []}}}):
            result = await services(str(workspace_with_token))
        assert result["count"] == 0
        assert result["services"] == []


# ===================================================================
# redeploy
# ===================================================================


class TestRedeploy:
    async def test_happy_path(self, workspace_with_token):
        redeploy_response = {
            "deploymentRedeploy": {"id": "dep-new", "status": "BUILDING"}
        }
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(DEPLOYMENT_EDGES, redeploy_response),
        ):
            result = await redeploy(str(workspace_with_token), "web")
        assert result["redeployed"] is True
        assert result["deploymentId"] == "dep-new"
        assert result["status"] == "BUILDING"

    async def test_no_deployments(self, workspace_with_token):
        with _patch_project(), _patch_service_id(), _patch_gql(DEPLOYMENT_EDGES_EMPTY):
            result = await redeploy(str(workspace_with_token), "web")
        assert "error" in result
        assert "No deployments" in result["error"]

    async def test_service_not_found(self, workspace_with_token):
        with _patch_project(), _patch_service_id(None):
            result = await redeploy(str(workspace_with_token), "ghost")
        assert "error" in result


# ===================================================================
# restart
# ===================================================================


class TestRestart:
    async def test_happy_path(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(DEPLOYMENT_EDGES, {"deploymentRestart": True}),
        ):
            result = await restart(str(workspace_with_token), "web")
        assert result["restarted"] is True
        assert result["deploymentId"] == "dep-001"
        assert result["service"] == "web"

    async def test_no_deployments(self, workspace_with_token):
        with _patch_project(), _patch_service_id(), _patch_gql(DEPLOYMENT_EDGES_EMPTY):
            result = await restart(str(workspace_with_token), "web")
        assert "error" in result


# ===================================================================
# domain
# ===================================================================


EMPTY_DOMAINS = {
    "serviceInstance": {"domains": {"serviceDomains": [], "customDomains": []}}
}

EXISTING_SERVICE_DOMAIN = {
    "serviceInstance": {
        "domains": {
            "serviceDomains": [{"id": "sd-1", "domain": "web-abc.up.railway.app"}],
            "customDomains": [],
        }
    }
}

EXISTING_CUSTOM_DOMAIN = {
    "serviceInstance": {
        "domains": {
            "serviceDomains": [],
            "customDomains": [{"id": "cd-1", "domain": "api.example.com"}],
        }
    }
}


class TestDomain:
    async def test_generate_railway_domain(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(
                EMPTY_DOMAINS,
                {
                    "serviceDomainCreate": {
                        "id": "dom-1",
                        "domain": "web-abc.up.railway.app",
                    }
                },
            ),
        ):
            result = await domain(str(workspace_with_token), "web")
        assert result["domain"] == "web-abc.up.railway.app"
        assert result["custom"] is False

    async def test_custom_domain(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(
                EMPTY_DOMAINS,
                {"customDomainCreate": {"id": "dom-2", "domain": "app.example.com"}},
            ),
        ):
            result = await domain(
                str(workspace_with_token), "web", domain="app.example.com"
            )
        assert result["domain"] == "app.example.com"
        assert result["custom"] is True

    async def test_with_port(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(
                EMPTY_DOMAINS,
                {
                    "serviceDomainCreate": {
                        "id": "dom-3",
                        "domain": "web.up.railway.app",
                    }
                },
            ) as mock_gql,
        ):
            await domain(str(workspace_with_token), "web", port=8080)
        # Verify targetPort was passed in the create call (second _gql call)
        call_args = mock_gql.call_args
        input_vars = call_args[0][2]["input"]
        assert input_vars["targetPort"] == 8080

    async def test_custom_domain_with_port(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(
                EMPTY_DOMAINS,
                {"customDomainCreate": {"id": "dom-4", "domain": "api.example.com"}},
            ) as mock_gql,
        ):
            await domain(
                str(workspace_with_token), "web", domain="api.example.com", port=3000
            )
        input_vars = mock_gql.call_args[0][2]["input"]
        assert input_vars["targetPort"] == 3000
        assert input_vars["domain"] == "api.example.com"

    async def test_service_not_found(self, workspace_with_token):
        with _patch_project(), _patch_service_id(None):
            result = await domain(str(workspace_with_token), "ghost")
        assert "error" in result

    # --- Update existing domain port ---

    async def test_update_existing_service_domain_port(self, workspace_with_token):
        """Existing railway.app domain + port => update targetPort via Bearer auth."""
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(EXISTING_SERVICE_DOMAIN),
            _patch_user_token(),
            _patch_gql_bearer({"serviceDomainUpdate": True}) as mock_bearer,
        ):
            result = await domain(str(workspace_with_token), "web", port=8000)
        assert result["updated"] is True
        assert result["targetPort"] == 8000
        assert result["domain"] == "web-abc.up.railway.app"
        assert result["custom"] is False
        # Verify the Bearer mutation was called with correct input
        call_args = mock_bearer.call_args[0]
        input_vars = call_args[2]["input"]
        assert input_vars["serviceDomainId"] == "sd-1"
        assert input_vars["targetPort"] == 8000
        assert input_vars["domain"] == "web-abc.up.railway.app"

    async def test_update_existing_custom_domain_port(self, workspace_with_token):
        """Existing custom domain + port => update targetPort via Bearer auth."""
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(EXISTING_CUSTOM_DOMAIN),
            _patch_user_token(),
            _patch_gql_bearer({"customDomainUpdate": True}) as mock_bearer,
        ):
            result = await domain(
                str(workspace_with_token), "web", domain="api.example.com", port=3000
            )
        assert result["updated"] is True
        assert result["targetPort"] == 3000
        assert result["domain"] == "api.example.com"
        assert result["custom"] is True
        # Verify customDomainId was used (not serviceDomainId)
        input_vars = mock_bearer.call_args[0][2]["input"]
        assert input_vars["customDomainId"] == "cd-1"

    async def test_existing_domain_no_port_returns_info(self, workspace_with_token):
        """Existing domain + no port => just return existing domain info."""
        with _patch_project(), _patch_service_id(), _patch_gql(EXISTING_SERVICE_DOMAIN):
            result = await domain(str(workspace_with_token), "web")
        assert result["existing"] is True
        assert result["domain"] == "web-abc.up.railway.app"
        assert result["custom"] is False
        assert "updated" not in result

    async def test_update_domain_no_account_token(self, workspace_with_token):
        """Update requires Bearer token — error if no account registered."""
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(EXISTING_SERVICE_DOMAIN),
            _patch_user_token_missing(),
        ):
            result = await domain(str(workspace_with_token), "web", port=8000)
        assert "error" in result
        assert "Bearer" in result["error"]

    async def test_update_domain_gql_error(self, workspace_with_token):
        """GraphQL error during update passes through."""
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(EXISTING_SERVICE_DOMAIN),
            _patch_user_token(),
            _patch_gql_bearer({"error": "unauthorized"}),
        ):
            result = await domain(str(workspace_with_token), "web", port=8000)
        assert result["error"] == "unauthorized"


# ===================================================================
# environment_create
# ===================================================================


class TestEnvironmentCreate:
    async def test_happy_path(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_gql({"environmentCreate": {"id": "env-new", "name": "staging"}}),
        ):
            result = await environment_create(str(workspace_with_token), "staging")
        assert result["created"] is True
        assert result["name"] == "staging"
        assert result["environmentId"] == "env-new"

    async def test_gql_error(self, workspace_with_token):
        with _patch_project(), _patch_gql({"error": "duplicate name"}):
            result = await environment_create(str(workspace_with_token), "staging")
        assert result["error"] == "duplicate name"


# ===================================================================
# deployments
# ===================================================================


class TestDeployments:
    async def test_happy_path(self, workspace_with_token):
        gql_response = {
            "deployments": {
                "edges": [
                    {
                        "node": {
                            "id": "dep-1",
                            "status": "SUCCESS",
                            "createdAt": "2026-01-01T00:00:00Z",
                            "url": None,
                            "staticUrl": None,
                            "canRedeploy": True,
                            "canRollback": True,
                        }
                    },
                    {
                        "node": {
                            "id": "dep-2",
                            "status": "FAILED",
                            "createdAt": "2025-12-31T00:00:00Z",
                            "url": None,
                            "staticUrl": None,
                            "canRedeploy": True,
                            "canRollback": False,
                        }
                    },
                ]
            }
        }
        with _patch_project(), _patch_service_id(), _patch_gql(gql_response):
            result = await deployments(str(workspace_with_token), "web")
        assert result["count"] == 2
        assert result["deployments"][0]["status"] == "SUCCESS"
        assert result["deployments"][1]["canRollback"] is False

    async def test_respects_limit(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql({"deployments": {"edges": []}}) as mock_gql,
        ):
            await deployments(str(workspace_with_token), "web", limit=5)
        call_args = mock_gql.call_args[0][2]
        assert call_args["first"] == 5


# ===================================================================
# rollback
# ===================================================================


class TestRollback:
    async def test_happy_path(self, workspace_with_token):
        with _patch_gql({"deploymentRollback": {"id": "dep-old", "status": "SUCCESS"}}):
            result = await rollback(str(workspace_with_token), "web", "dep-old")
        assert result["deploymentRollback"]["id"] == "dep-old"

    async def test_gql_error(self, workspace_with_token):
        with _patch_gql({"error": "deployment not found"}):
            result = await rollback(str(workspace_with_token), "web", "dep-bad")
        assert result["error"] == "deployment not found"


# ===================================================================
# service_info
# ===================================================================


class TestServiceInfo:
    async def test_happy_path(self, workspace_with_token):
        instance_data = {
            "serviceInstance": {
                "id": "si-1",
                "serviceName": "web",
                "startCommand": "node server.js",
                "buildCommand": "npm run build",
                "rootDirectory": "/",
                "healthcheckPath": "/health",
                "region": "us-west1",
                "numReplicas": 1,
                "restartPolicyType": "ON_FAILURE",
                "restartPolicyMaxRetries": 10,
                "latestDeployment": {
                    "id": "dep-1",
                    "status": "SUCCESS",
                    "createdAt": "2026-01-01",
                    "url": None,
                },
            }
        }
        with _patch_project(), _patch_service_id(), _patch_gql(instance_data):
            result = await service_info(str(workspace_with_token), "web")
        assert result["serviceName"] == "web"
        assert result["startCommand"] == "node server.js"
        assert result["region"] == "us-west1"
        assert result["numReplicas"] == 1


# ===================================================================
# http_logs
# ===================================================================


class TestHttpLogs:
    async def test_with_deployment_id(self, workspace_with_token):
        log_data = {
            "httpLogs": [
                {
                    "timestamp": "2026-01-01T00:00:00Z",
                    "method": "GET",
                    "path": "/",
                    "httpStatus": 200,
                    "totalDuration": 12,
                    "requestId": "r1",
                    "srcIp": "1.2.3.4",
                },
            ]
        }
        with _patch_gql(log_data):
            result = await http_logs(
                str(workspace_with_token), "web", deployment_id="dep-001"
            )
        assert result["count"] == 1
        assert result["logs"][0]["httpStatus"] == 200
        assert result["deployment_id"] == "dep-001"

    async def test_auto_resolve_deployment(self, workspace_with_token):
        log_data = {"httpLogs": []}
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(DEPLOYMENT_EDGES, log_data),
        ):
            result = await http_logs(str(workspace_with_token), "web")
        assert result["deployment_id"] == "dep-001"
        assert result["count"] == 0

    async def test_no_deployments(self, workspace_with_token):
        with _patch_project(), _patch_service_id(), _patch_gql(DEPLOYMENT_EDGES_EMPTY):
            result = await http_logs(str(workspace_with_token), "web")
        assert "error" in result


# ===================================================================
# deployment_logs
# ===================================================================


class TestDeploymentLogs:
    async def test_deploy_logs(self, workspace_with_token):
        log_entries = {
            "deploymentLogs": [
                {
                    "message": "Starting server",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "severity": "info",
                },
                {
                    "message": "Listening on :3000",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "severity": "info",
                },
            ]
        }
        with _patch_gql(log_entries):
            result = await deployment_logs(str(workspace_with_token), "dep-123")
        assert result["count"] == 2
        assert result["deploymentId"] == "dep-123"
        assert result["logs"][0]["message"] == "Starting server"

    async def test_build_logs(self, workspace_with_token):
        log_entries = {
            "buildLogs": [
                {
                    "message": "Installing deps...",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "severity": "info",
                },
            ]
        }
        with _patch_gql(log_entries):
            result = await deployment_logs(
                str(workspace_with_token), "dep-123", build=True
            )
        assert result["count"] == 1
        assert result["logs"][0]["message"] == "Installing deps..."

    async def test_with_filter(self, workspace_with_token):
        with _patch_gql({"deploymentLogs": []}) as mock_gql:
            await deployment_logs(str(workspace_with_token), "dep-123", filter="ERROR")
        gql_vars = mock_gql.call_args[0][2]
        assert gql_vars["filter"] == "ERROR"

    async def test_with_limit(self, workspace_with_token):
        with _patch_gql({"deploymentLogs": []}) as mock_gql:
            await deployment_logs(str(workspace_with_token), "dep-123", limit=25)
        gql_vars = mock_gql.call_args[0][2]
        assert gql_vars["limit"] == 25

    async def test_gql_error(self, workspace_with_token):
        with _patch_gql({"error": "deployment not found"}):
            result = await deployment_logs(str(workspace_with_token), "dep-bad")
        assert result["error"] == "deployment not found"

    async def test_no_token(self, workspace):
        with pytest.raises(ValueError, match="RAILWAY_TOKEN"):
            await deployment_logs(str(workspace), "dep-123")


# ===================================================================
# unlink_repo
# ===================================================================


class TestUnlinkRepo:
    async def test_happy_path(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql({"serviceDisconnect": {"id": "svc-111"}}),
        ):
            result = await unlink_repo(str(workspace_with_token), "web")
        assert result["disconnected"] is True
        assert result["service"] == "web"
        assert "GitHub repo linking removed" in result["next_step"]

    async def test_service_not_found(self, workspace_with_token):
        with _patch_project(), _patch_service_id(None):
            result = await unlink_repo(str(workspace_with_token), "ghost")
        assert "error" in result


# ===================================================================
# Cross-cutting: missing token
# ===================================================================


# ===================================================================
# service_update
# ===================================================================


def _patch_gql_bearer(*responses):
    """Patch _gql_bearer with sequential responses (side_effect) or a single one."""
    if len(responses) == 1:
        return patch(
            "railguey.lib.tools._gql_bearer",
            new_callable=AsyncMock,
            return_value=responses[0],
        )
    return patch(
        "railguey.lib.tools._gql_bearer",
        new_callable=AsyncMock,
        side_effect=list(responses),
    )


def _patch_user_token(token: str = "user-token-abc"):
    return patch(
        "railguey.lib.tools._load_user_token",
        return_value=token,
    )


def _patch_user_token_missing():
    return patch(
        "railguey.lib.tools._load_user_token",
        side_effect=ValueError("No Railway account token found"),
    )


class _FakeUploadResponse:
    status_code = 404
    text = "Service instance not found"

    def json(self):
        return {"message": "Service instance not found"}


class _FakeUploadClient:
    def __init__(self, *args, **kwargs):
        self.post_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, *args, **kwargs):
        self.post_calls.append((args, kwargs))
        return _FakeUploadResponse()


class TestUploadSource:
    async def test_404_service_instance_mismatch_is_diagnosed(
        self, workspace_with_token
    ):
        """A cross-env token mismatch should not look like a generic 404."""
        project_topology = {
            "project": {
                "environments": {
                    "edges": [
                        {"node": {"id": "env-xyz", "name": "develop"}},
                        {"node": {"id": "env-prod", "name": "production"}},
                    ]
                },
                "services": {
                    "edges": [
                        {
                            "node": {
                                "id": "svc-111",
                                "name": "dd4t",
                                "serviceInstances": {
                                    "edges": [{"node": {"environmentId": "env-prod"}}]
                                },
                            }
                        }
                    ]
                },
            }
        }

        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(project_topology),
            patch("httpx.AsyncClient", _FakeUploadClient),
        ):
            result = await upload_source(str(workspace_with_token), "dd4t")

        assert result["diagnostic"] == "service_instance_environment_mismatch"
        assert "develop" in result["error"]
        assert "production" in result["error"]
        assert result["railwayError"] == "Service instance not found"
        assert result["serviceInstanceBindings"] == [
            {"environmentId": "env-prod", "environmentName": "production"}
        ]

    async def test_404_falls_back_when_no_cross_env_evidence(
        self, workspace_with_token
    ):
        """If topology does not explain the 404, preserve the raw Railway error."""
        project_topology = {
            "project": {
                "environments": {"edges": []},
                "services": {
                    "edges": [
                        {
                            "node": {
                                "id": "svc-111",
                                "name": "dd4t",
                                "serviceInstances": {"edges": []},
                            }
                        }
                    ]
                },
            }
        }

        with (
            _patch_project(),
            _patch_service_id(),
            _patch_gql(project_topology),
            patch("httpx.AsyncClient", _FakeUploadClient),
        ):
            result = await upload_source(str(workspace_with_token), "dd4t")

        assert result["error"] == "Upload failed (HTTP 404): Service instance not found"
        assert "diagnostic" not in result


class TestServiceUpdate:
    async def test_set_healthcheck(self, workspace_with_token):
        """Happy path: set a single field (healthcheckPath)."""
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_user_token(),
            _patch_gql_bearer({"serviceInstanceUpdate": True}) as mock_bearer,
        ):
            result = await service_update(
                str(workspace_with_token), "web", healthcheck_path="/health"
            )
        assert result["updated"] is True
        assert result["service"] == "web"
        assert result["fields"] == {"healthcheckPath": "/health"}
        # Verify the mutation was called with correct args
        call_args = mock_bearer.call_args[0]
        assert call_args[0] == "user-token-abc"  # Bearer token
        gql_vars = call_args[2]
        assert gql_vars["input"] == {"healthcheckPath": "/health"}
        assert gql_vars["serviceId"] == "svc-111"
        assert gql_vars["environmentId"] == "env-xyz"

    async def test_multiple_fields(self, workspace_with_token):
        """Set multiple fields at once."""
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_user_token(),
            _patch_gql_bearer({"serviceInstanceUpdate": True}),
        ):
            result = await service_update(
                str(workspace_with_token),
                "web",
                healthcheck_path="/health",
                start_command="node server.js",
                num_replicas=2,
                region="us-west1",
            )
        assert result["updated"] is True
        assert result["fields"] == {
            "healthcheckPath": "/health",
            "startCommand": "node server.js",
            "numReplicas": 2,
            "region": "us-west1",
        }

    async def test_no_fields_error(self, workspace_with_token):
        """Error when no fields are provided."""
        result = await service_update(str(workspace_with_token), "web")
        assert "error" in result
        assert "No fields to update" in result["error"]

    async def test_no_account_token_error(self, workspace_with_token):
        """Error when no account token is available."""
        with _patch_project(), _patch_service_id(), _patch_user_token_missing():
            result = await service_update(
                str(workspace_with_token), "web", healthcheck_path="/health"
            )
        assert "error" in result
        assert "Bearer" in result["error"]
        assert "account" in result["error"]

    async def test_service_not_found(self, workspace_with_token):
        """Error when service name doesn't match any service."""
        with _patch_project(), _patch_service_id(None):
            result = await service_update(
                str(workspace_with_token), "ghost", healthcheck_path="/health"
            )
        assert "error" in result
        assert "ghost" in result["error"]

    async def test_project_error_passthrough(self, workspace_with_token):
        """Project resolution errors pass through."""
        with _patch_project({"error": "bad token"}):
            result = await service_update(
                str(workspace_with_token), "web", healthcheck_path="/health"
            )
        assert result == {"error": "bad token"}

    async def test_gql_bearer_error(self, workspace_with_token):
        """GraphQL mutation errors pass through."""
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_user_token(),
            _patch_gql_bearer({"error": "unauthorized"}),
        ):
            result = await service_update(
                str(workspace_with_token), "web", healthcheck_path="/health"
            )
        assert result["error"] == "unauthorized"

    async def test_all_fields(self, workspace_with_token):
        """All 8 fields can be set at once."""
        with (
            _patch_project(),
            _patch_service_id(),
            _patch_user_token(),
            _patch_gql_bearer({"serviceInstanceUpdate": True}),
        ):
            result = await service_update(
                str(workspace_with_token),
                "web",
                healthcheck_path="/health",
                start_command="node start",
                build_command="npm run build",
                root_directory="/app",
                region="us-east4",
                num_replicas=3,
                restart_policy_type="ON_FAILURE",
                restart_policy_max_retries=5,
            )
        assert result["updated"] is True
        fields = result["fields"]
        assert fields["healthcheckPath"] == "/health"
        assert fields["startCommand"] == "node start"
        assert fields["buildCommand"] == "npm run build"
        assert fields["rootDirectory"] == "/app"
        assert fields["region"] == "us-east4"
        assert fields["numReplicas"] == 3
        assert fields["restartPolicyType"] == "ON_FAILURE"
        assert fields["restartPolicyMaxRetries"] == 5


# ===================================================================
# buckets
# ===================================================================


BUCKET_TOPOLOGY = {
    "project": {
        "id": "proj-abc",
        "name": "proj",
        "buckets": {
            "edges": [
                {
                    "node": {
                        "id": "bucket-1",
                        "name": "photos",
                        "projectId": "proj-abc",
                        "createdAt": "2026-05-01T00:00:00Z",
                        "updatedAt": "2026-05-01T00:00:00Z",
                    }
                }
            ]
        },
        "environments": {
            "edges": [
                {
                    "node": {
                        "id": "env-xyz",
                        "name": "production",
                        "unmergedChangesCount": 0,
                        "config": {
                            "buckets": {
                                "bucket-1": {
                                    "region": "iad",
                                    "isCreated": True,
                                }
                            }
                        },
                    }
                }
            ]
        },
    }
}


class TestBuckets:
    async def test_list_buckets(self, workspace_with_token):
        with _patch_project(), _patch_gql(BUCKET_TOPOLOGY):
            result = await buckets(str(workspace_with_token))

        assert result["count"] == 1
        assert result["buckets"][0]["name"] == "photos"
        assert result["buckets"][0]["region"] == "iad"

    async def test_create_bucket_commits_environment_patch(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_user_token(),
            _patch_gql(
                {"environment": {"id": "env-xyz", "unmergedChangesCount": 0}},
                {"environmentPatchCommit": True},
            ) as mock_gql,
            _patch_gql_bearer(
                {
                    "bucketCreate": {
                        "id": "bucket-2",
                        "name": "omnidata",
                        "projectId": "proj-abc",
                    }
                }
            ),
        ):
            result = await bucket_create(str(workspace_with_token), "omnidata", "iad")

        assert result["created"] is True
        assert result["bucketId"] == "bucket-2"
        assert result["region"] == "iad"
        assert result["committed"] is True
        patch_vars = mock_gql.call_args_list[1].args[2]
        assert patch_vars["patch"]["buckets"]["bucket-2"] == {
            "region": "iad",
            "isCreated": True,
        }

    async def test_create_bucket_stages_when_environment_has_changes(
        self, workspace_with_token
    ):
        with (
            _patch_project(),
            _patch_user_token(),
            _patch_gql(
                {"environment": {"id": "env-xyz", "unmergedChangesCount": 2}},
                {"environmentStageChanges": {"id": "change-1", "status": "STAGED"}},
            ) as mock_gql,
            _patch_gql_bearer(
                {
                    "bucketCreate": {
                        "id": "bucket-2",
                        "name": "omnidata",
                        "projectId": "proj-abc",
                    }
                }
            ),
        ):
            result = await bucket_create(str(workspace_with_token), "omnidata", "sjc")

        assert result["staged"] is True
        stage_vars = mock_gql.call_args_list[1].args[2]
        assert stage_vars["merge"] is True
        assert stage_vars["input"]["buckets"]["bucket-2"]["region"] == "sjc"

    async def test_create_rejects_invalid_region(self, workspace_with_token):
        result = await bucket_create(str(workspace_with_token), "bad", "dfw")
        assert "Invalid bucket region" in result["error"]

    async def test_info_merges_topology_and_details(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_gql(
                BUCKET_TOPOLOGY,
                {"bucketInstanceDetails": {"sizeBytes": "1024", "objectCount": "3"}},
            ),
        ):
            result = await bucket_info(str(workspace_with_token), "photos")

        assert result["id"] == "bucket-1"
        assert result["sizeBytes"] == 1024
        assert result["objectCount"] == 3

    async def test_credentials_returns_s3_env_shape(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_gql(
                BUCKET_TOPOLOGY,
                {
                    "bucketS3Credentials": [
                        {
                            "accessKeyId": "access",
                            "secretAccessKey": "secret",
                            "endpoint": "https://storage.railway.app",
                            "bucketName": "photos-hash",
                            "region": "auto",
                            "urlStyle": "virtual-hosted",
                        }
                    ]
                },
            ),
        ):
            result = await bucket_credentials(str(workspace_with_token), "photos")

        assert result["credentials"]["AWS_S3_BUCKET_NAME"] == "photos-hash"
        assert result["credentials"]["AWS_SECRET_ACCESS_KEY"] == "secret"

    async def test_credentials_reset_uses_mutation(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_user_token(),
            _patch_gql(
                BUCKET_TOPOLOGY,
            ),
            _patch_gql_bearer(
                {
                    "bucketCredentialsReset": {
                        "accessKeyId": "access2",
                        "secretAccessKey": "secret2",
                        "endpoint": "https://storage.railway.app",
                        "bucketName": "photos-hash",
                        "region": "auto",
                        "urlStyle": "virtual-hosted",
                    }
                }
            ) as mock_bearer,
        ):
            result = await bucket_credentials(
                str(workspace_with_token), "photos", reset=True
            )

        assert result["reset"] is True
        assert "bucketCredentialsReset" in mock_bearer.call_args.args[1]

    async def test_rename_bucket(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_user_token(),
            _patch_gql(
                BUCKET_TOPOLOGY,
            ),
            _patch_gql_bearer(
                {
                    "bucketUpdate": {
                        "id": "bucket-1",
                        "name": "archive",
                        "projectId": "proj-abc",
                    }
                }
            ),
        ):
            result = await bucket_rename(str(workspace_with_token), "photos", "archive")

        assert result["renamed"] is True
        assert result["oldName"] == "photos"
        assert result["bucketName"] == "archive"

    async def test_delete_bucket_patches_environment(self, workspace_with_token):
        with (
            _patch_project(),
            _patch_gql(
                BUCKET_TOPOLOGY,
                {"environment": {"id": "env-xyz", "unmergedChangesCount": 0}},
                {"environmentPatchCommit": True},
            ) as mock_gql,
        ):
            result = await bucket_delete(str(workspace_with_token), "photos")

        assert result["deleted"] is True
        patch_vars = mock_gql.call_args_list[2].args[2]
        assert patch_vars["patch"]["buckets"]["bucket-1"] == {"isDeleted": True}


# ===================================================================
# Cross-cutting: missing token
# ===================================================================


class TestMissingToken:
    async def test_status_no_token(self, workspace):
        with pytest.raises(ValueError, match="RAILWAY_TOKEN"):
            await status(str(workspace))

    async def test_logs_no_token(self, workspace):
        with pytest.raises(ValueError, match="RAILWAY_TOKEN"):
            await logs(str(workspace), "web")

    async def test_deploy_no_token(self, workspace):
        with pytest.raises(ValueError, match="RAILWAY_TOKEN"):
            await deploy(str(workspace), "web")
