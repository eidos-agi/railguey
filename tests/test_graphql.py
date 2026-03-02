"""Tests for the GraphQL backend (Backboard API)."""

import pytest
from unittest.mock import AsyncMock, patch

from railguey.lib.graphql import _gql, _resolve_project, _resolve_service_id
from tests.helpers import mock_httpx_response, mock_httpx_client, PROJECT_DATA, SERVICES_DATA


class TestGql:
    @pytest.mark.asyncio
    async def test_successful_query(self):
        resp = mock_httpx_response({
            "data": {"projectToken": {"projectId": "proj-123", "environmentId": "env-456"}}
        })
        client = mock_httpx_client(resp)

        with patch("railguey.lib.graphql.httpx.AsyncClient", return_value=client):
            result = await _gql("token", "query { projectToken { projectId } }")

        assert result == {"projectToken": {"projectId": "proj-123", "environmentId": "env-456"}}

    @pytest.mark.asyncio
    async def test_graphql_error(self):
        resp = mock_httpx_response({"errors": [{"message": "Not authorized"}]})
        client = mock_httpx_client(resp)

        with patch("railguey.lib.graphql.httpx.AsyncClient", return_value=client):
            result = await _gql("bad-token", "query { projectToken { projectId } }")

        assert result["error"] == "GraphQL error"
        assert "Not authorized" in str(result["details"])

    @pytest.mark.asyncio
    async def test_uses_project_access_token_header(self):
        resp = mock_httpx_response({"data": {}})
        client = mock_httpx_client(resp)

        with patch("railguey.lib.graphql.httpx.AsyncClient", return_value=client):
            await _gql("my-secret-token", "query { test }")

        call_kwargs = client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Project-Access-Token"] == "my-secret-token"
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_passes_variables(self):
        resp = mock_httpx_response({"data": {"deployments": []}})
        client = mock_httpx_client(resp)

        with patch("railguey.lib.graphql.httpx.AsyncClient", return_value=client):
            await _gql("token", "query q($id: String!) { test }", {"id": "abc"})

        call_kwargs = client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["variables"] == {"id": "abc"}


class TestResolveProject:
    @pytest.mark.asyncio
    async def test_returns_project_and_env_ids(self):
        with patch("railguey.lib.graphql._gql", new_callable=AsyncMock) as mock:
            mock.return_value = {"projectToken": PROJECT_DATA}
            result = await _resolve_project("token")
        assert result["projectId"] == "proj-abc"
        assert result["environmentId"] == "env-xyz"

    @pytest.mark.asyncio
    async def test_passes_through_errors(self):
        with patch("railguey.lib.graphql._gql", new_callable=AsyncMock) as mock:
            mock.return_value = {"error": "Unauthorized"}
            result = await _resolve_project("bad-token")
        assert result == {"error": "Unauthorized"}


class TestResolveServiceId:
    @pytest.mark.asyncio
    async def test_finds_service_by_name(self):
        with patch("railguey.lib.graphql._gql", new_callable=AsyncMock) as mock:
            mock.return_value = SERVICES_DATA
            result = await _resolve_service_id("token", "proj-abc", "worker")
        assert result == "svc-222"

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self):
        with patch("railguey.lib.graphql._gql", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "project": {
                    "services": {"edges": [{"node": {"id": "svc-111", "name": "Cerebro"}}]}
                }
            }
            result = await _resolve_service_id("token", "proj-abc", "cerebro")
        assert result == "svc-111"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        with patch("railguey.lib.graphql._gql", new_callable=AsyncMock) as mock:
            mock.return_value = SERVICES_DATA
            result = await _resolve_service_id("token", "proj-abc", "nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        with patch("railguey.lib.graphql._gql", new_callable=AsyncMock) as mock:
            mock.return_value = {"error": "Something broke"}
            result = await _resolve_service_id("token", "proj-abc", "web")
        assert result is None
