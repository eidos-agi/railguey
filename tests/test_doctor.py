"""Tests for railguey_doctor workspace audit."""

import pytest
from unittest.mock import AsyncMock, patch
from pathlib import Path

from server import railguey_doctor


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


class TestDoctor:
    @pytest.mark.asyncio
    async def test_no_token_fails(self, tmp_path):
        result = await railguey_doctor(str(tmp_path))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["RAILWAY_TOKEN"]["status"] == "fail"
        assert result["healthy"] is False

    @pytest.mark.asyncio
    async def test_token_present_passes(self, tmp_path):
        _write(tmp_path / ".env.local", "RAILWAY_TOKEN=test-123\n")
        with patch("server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(tmp_path))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["RAILWAY_TOKEN"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_gitignore_missing_warns(self, tmp_path):
        _write(tmp_path / ".env.local", "RAILWAY_TOKEN=test-123\n")
        with patch("server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(tmp_path))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks[".gitignore"]["status"] == "warn"

    @pytest.mark.asyncio
    async def test_gitignore_with_env_local_passes(self, tmp_path):
        _write(tmp_path / ".env.local", "RAILWAY_TOKEN=test-123\n")
        _write(tmp_path / ".gitignore", "node_modules/\n.env.local\n")
        with patch("server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(tmp_path))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks[".gitignore"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_deploy_workflow_detected(self, tmp_path):
        _write(tmp_path / ".env.local", "RAILWAY_TOKEN=test-123\n")
        _write(tmp_path / ".gitignore", ".env.local\n")
        _write(
            tmp_path / ".github" / "workflows" / "deploy.yml",
            "name: Deploy\non:\n  push:\njobs:\n  deploy:\n    env:\n      RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n    run: railway up\n",
        )
        with patch("server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(tmp_path))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["CI/CD workflow"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_no_deploy_workflow_warns(self, tmp_path):
        _write(tmp_path / ".env.local", "RAILWAY_TOKEN=test-123\n")
        _write(tmp_path / ".gitignore", ".env.local\n")
        with patch("server._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await railguey_doctor(str(tmp_path))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["CI/CD workflow"]["status"] == "warn"

    @pytest.mark.asyncio
    async def test_perfect_score(self, tmp_path):
        _write(tmp_path / ".env.local", "RAILWAY_TOKEN=test-123\n")
        _write(tmp_path / ".gitignore", ".env.local\n")
        _write(
            tmp_path / ".github" / "workflows" / "deploy.yml",
            "RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\nrailway up\n",
        )
        with (
            patch("server._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("server._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = {"projectId": "proj-1", "environmentId": "env-1"}
            mock_gql.return_value = {
                "project": {
                    "services": {
                        "edges": [{"node": {"id": "svc-1", "name": "web"}}]
                    }
                }
            }
            # Second call for service repo triggers — no triggers = good
            mock_gql.side_effect = [
                mock_gql.return_value,  # project query
                {"service": {"id": "svc-1", "name": "web", "repoTriggers": []}},  # service query
            ]
            result = await railguey_doctor(str(tmp_path))

        assert result["score"] == "4/4"
        assert result["healthy"] is True

    @pytest.mark.asyncio
    async def test_linked_repo_warns(self, tmp_path):
        _write(tmp_path / ".env.local", "RAILWAY_TOKEN=test-123\n")
        _write(tmp_path / ".gitignore", ".env.local\n")
        with (
            patch("server._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("server._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = {"projectId": "proj-1", "environmentId": "env-1"}
            mock_gql.side_effect = [
                {"project": {"services": {"edges": [{"node": {"id": "svc-1", "name": "web"}}]}}},
                {"service": {"id": "svc-1", "name": "web", "repoTriggers": [{"repository": "org/repo", "branch": "main"}]}},
            ]
            result = await railguey_doctor(str(tmp_path))

        checks = {f["check"]: f for f in result["findings"]}
        assert checks["GitHub repo linking"]["status"] == "warn"
        assert checks["GitHub repo linking"]["linked"][0]["repo"] == "org/repo"
