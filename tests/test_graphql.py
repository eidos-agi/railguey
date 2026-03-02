"""Tests for the GraphQL backend (Backboard API)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from server import _gql, _resolve_project, _resolve_service_id


def _mock_response(json_data, status_code=200):
    """Create a mock httpx Response (sync methods like .json())."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


def _mock_client(response):
    """Create a mock httpx.AsyncClient that returns the given response on post."""
    client = AsyncMock()
    client.post.return_value = response
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


class TestGql:
    @pytest.mark.asyncio
    async def test_successful_query(self):
        resp = _mock_response({
            "data": {"projectToken": {"projectId": "proj-123", "environmentId": "env-456"}}
        })
        client = _mock_client(resp)

        with patch("server.httpx.AsyncClient", return_value=client):
            result = await _gql("token", "query { projectToken { projectId } }")

        assert result == {"projectToken": {"projectId": "proj-123", "environmentId": "env-456"}}

    @pytest.mark.asyncio
    async def test_graphql_error(self):
        resp = _mock_response({"errors": [{"message": "Not authorized"}]})
        client = _mock_client(resp)

        with patch("server.httpx.AsyncClient", return_value=client):
            result = await _gql("bad-token", "query { projectToken { projectId } }")

        assert result["error"] == "GraphQL error"
        assert "Not authorized" in str(result["details"])

    @pytest.mark.asyncio
    async def test_uses_project_access_token_header(self):
        resp = _mock_response({"data": {}})
        client = _mock_client(resp)

        with patch("server.httpx.AsyncClient", return_value=client):
            await _gql("my-secret-token", "query { test }")

        call_kwargs = client.post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["Project-Access-Token"] == "my-secret-token"
        assert "Authorization" not in headers

    @pytest.mark.asyncio
    async def test_passes_variables(self):
        resp = _mock_response({"data": {"deployments": []}})
        client = _mock_client(resp)

        with patch("server.httpx.AsyncClient", return_value=client):
            await _gql("token", "query q($id: String!) { test }", {"id": "abc"})

        call_kwargs = client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["variables"] == {"id": "abc"}


class TestResolveProject:
    @pytest.mark.asyncio
    async def test_returns_project_and_env_ids(self):
        with patch("server._gql", new_callable=AsyncMock) as mock_gql:
            mock_gql.return_value = {
                "projectToken": {"projectId": "proj-abc", "environmentId": "env-xyz"}
            }
            result = await _resolve_project("token")

        assert result["projectId"] == "proj-abc"
        assert result["environmentId"] == "env-xyz"

    @pytest.mark.asyncio
    async def test_passes_through_errors(self):
        with patch("server._gql", new_callable=AsyncMock) as mock_gql:
            mock_gql.return_value = {"error": "Unauthorized"}
            result = await _resolve_project("bad-token")

        assert result == {"error": "Unauthorized"}


class TestResolveServiceId:
    @pytest.mark.asyncio
    async def test_finds_service_by_name(self):
        with patch("server._gql", new_callable=AsyncMock) as mock_gql:
            mock_gql.return_value = {
                "project": {
                    "services": {
                        "edges": [
                            {"node": {"id": "svc-111", "name": "web"}},
                            {"node": {"id": "svc-222", "name": "worker"}},
                        ]
                    }
                }
            }
            result = await _resolve_service_id("token", "proj-abc", "worker")

        assert result == "svc-222"

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self):
        with patch("server._gql", new_callable=AsyncMock) as mock_gql:
            mock_gql.return_value = {
                "project": {
                    "services": {
                        "edges": [{"node": {"id": "svc-111", "name": "Cerebro"}}]
                    }
                }
            }
            result = await _resolve_service_id("token", "proj-abc", "cerebro")

        assert result == "svc-111"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        with patch("server._gql", new_callable=AsyncMock) as mock_gql:
            mock_gql.return_value = {
                "project": {
                    "services": {
                        "edges": [{"node": {"id": "svc-111", "name": "web"}}]
                    }
                }
            }
            result = await _resolve_service_id("token", "proj-abc", "nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_api_error(self):
        with patch("server._gql", new_callable=AsyncMock) as mock_gql:
            mock_gql.return_value = {"error": "Something broke"}
            result = await _resolve_service_id("token", "proj-abc", "web")

        assert result is None
