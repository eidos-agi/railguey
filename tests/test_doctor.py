"""Tests for railguey_doctor workspace audit."""

import pytest
from unittest.mock import AsyncMock, patch

from railguey.server import railguey_doctor
from tests.helpers import write_file


class TestDoctor:
    @pytest.mark.asyncio
    async def test_no_token_fails(self, workspace):
        result = await railguey_doctor(str(workspace))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["RAILWAY_TOKEN"]["status"] == "fail"
        assert result["healthy"] is False

    @pytest.mark.asyncio
    async def test_token_present_passes(self, workspace_with_token):
        with patch("railguey.server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["RAILWAY_TOKEN"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_gitignore_missing_warns(self, workspace_with_token):
        with patch("railguey.server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks[".gitignore"]["status"] == "warn"

    @pytest.mark.asyncio
    async def test_gitignore_with_env_local_passes(self, workspace_with_token):
        write_file(workspace_with_token / ".gitignore", "node_modules/\n.env.local\n")
        with patch("railguey.server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks[".gitignore"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_deploy_workflow_detected(self, workspace_healthy):
        with patch("railguey.server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(workspace_healthy))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["CI/CD workflow"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_no_deploy_workflow_warns(self, workspace_with_token):
        write_file(workspace_with_token / ".gitignore", ".env.local\n")
        with patch("railguey.server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["CI/CD workflow"]["status"] == "warn"

    @pytest.mark.asyncio
    async def test_perfect_score(self, workspace_healthy):
        with (
            patch("railguey.server._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("railguey.server._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = {"projectId": "proj-1", "environmentId": "env-1"}
            mock_gql.side_effect = [
                {"project": {"services": {"edges": [{"node": {"id": "svc-1", "name": "web"}}]}}},
                {"service": {"id": "svc-1", "name": "web", "repoTriggers": []}},
            ]
            result = await railguey_doctor(str(workspace_healthy))
        assert result["score"] == "4/4"
        assert result["healthy"] is True

    @pytest.mark.asyncio
    async def test_linked_repo_warns(self, workspace_with_token):
        write_file(workspace_with_token / ".gitignore", ".env.local\n")
        with (
            patch("railguey.server._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("railguey.server._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = {"projectId": "proj-1", "environmentId": "env-1"}
            mock_gql.side_effect = [
                {"project": {"services": {"edges": [{"node": {"id": "svc-1", "name": "web"}}]}}},
                {"service": {"id": "svc-1", "name": "web", "repoTriggers": [{"repository": "org/repo", "branch": "main"}]}},
            ]
            result = await railguey_doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["GitHub repo linking"]["status"] == "warn"
        assert checks["GitHub repo linking"]["linked"][0]["repo"] == "org/repo"
