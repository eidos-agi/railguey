"""Tests for railguey_doctor workspace audit."""

import pytest
from unittest.mock import AsyncMock, patch

from railguey.lib.doctor import doctor, _parse_workflow_details
from tests.helpers import write_file


# ---------------------------------------------------------------------------
# _parse_workflow_details unit tests
# ---------------------------------------------------------------------------


class TestParseWorkflowDetails:
    def test_no_workflows_dir(self, tmp_path):
        result = _parse_workflow_details(tmp_path / ".github" / "workflows")
        assert result["found"] is False

    def test_single_branch_single_env(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        write_file(wf_dir / "deploy.yml", (
            "name: Deploy\n"
            "on:\n"
            "  push:\n"
            "    branches: [main]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: railway up --service cerebro --environment production --detach\n"
            "        env:\n"
            "          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n"
        ))
        result = _parse_workflow_details(wf_dir)
        assert result["found"] is True
        assert result["branches"] == ["main"]
        assert result["environments"] == ["production"]
        assert result["services"] == ["cerebro"]

    def test_multi_branch_multi_env(self, tmp_path):
        wf_dir = tmp_path / ".github" / "workflows"
        write_file(wf_dir / "deploy.yml", (
            "name: Deploy\n"
            "on:\n"
            "  push:\n"
            "    branches: [main, develop]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: |\n"
            "          if [ branch = main ]; then\n"
            "            railway up --service cerebro --environment production --detach\n"
            "          else\n"
            "            railway up --service cerebro --environment develop --detach\n"
            "          fi\n"
            "        env:\n"
            "          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n"
        ))
        result = _parse_workflow_details(wf_dir)
        assert result["found"] is True
        assert sorted(result["branches"]) == ["develop", "main"]
        assert result["environments"] == ["develop", "production"]
        assert result["services"] == ["cerebro"]

    def test_single_branch_but_multi_env_detected(self, tmp_path):
        """Workflow targets 2 environments but only triggers on 1 branch."""
        wf_dir = tmp_path / ".github" / "workflows"
        write_file(wf_dir / "deploy.yml", (
            "name: Deploy\n"
            "on:\n"
            "  push:\n"
            "    branches: [main]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: |\n"
            "          railway up --service cerebro --environment production --detach\n"
            "          railway up --service cerebro --environment develop --detach\n"
            "        env:\n"
            "          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n"
        ))
        result = _parse_workflow_details(wf_dir)
        assert result["branches"] == ["main"]
        assert result["environments"] == ["develop", "production"]

    def test_no_environment_flag(self, tmp_path):
        """Workflow without --environment is a simple single-env setup."""
        wf_dir = tmp_path / ".github" / "workflows"
        write_file(wf_dir / "deploy.yml", (
            "name: Deploy\n"
            "on:\n"
            "  push:\n"
            "    branches: [main]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: railway up --service web --detach\n"
            "        env:\n"
            "          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n"
        ))
        result = _parse_workflow_details(wf_dir)
        assert result["found"] is True
        assert result["environments"] == []
        assert result["services"] == ["web"]


# ---------------------------------------------------------------------------
# Full doctor integration tests
# ---------------------------------------------------------------------------


def _mock_project_and_envs(token_env_name="production"):
    """Return mock side effects for _resolve_project and _gql.

    Railway environments: production + develop.
    Token scoped to token_env_name.
    """
    env_map = {"env-prod": "production", "env-dev": "develop"}
    token_env_id = next(k for k, v in env_map.items() if v == token_env_name)

    project_return = {"projectId": "proj-1", "environmentId": token_env_id}
    gql_project = {
        "project": {
            "environments": {
                "edges": [
                    {"node": {"id": eid, "name": ename}}
                    for eid, ename in env_map.items()
                ]
            },
            "services": {
                "edges": [{"node": {"id": "svc-1", "name": "cerebro"}}]
            },
        }
    }
    gql_service = {
        "service": {"id": "svc-1", "name": "cerebro", "repoTriggers": []}
    }
    return project_return, [gql_project, gql_service]


class TestDoctor:
    @pytest.mark.asyncio
    async def test_no_token_fails(self, workspace):
        result = await doctor(str(workspace))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["RAILWAY_TOKEN"]["status"] == "fail"
        assert result["healthy"] is False

    @pytest.mark.asyncio
    async def test_token_present_passes(self, workspace_with_token):
        with patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["RAILWAY_TOKEN"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_gitignore_missing_warns(self, workspace_with_token):
        with patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks[".gitignore"]["status"] == "warn"

    @pytest.mark.asyncio
    async def test_gitignore_with_env_local_passes(self, workspace_with_token):
        write_file(workspace_with_token / ".gitignore", "node_modules/\n.env.local\n")
        with patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks[".gitignore"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_deploy_workflow_detected(self, workspace_healthy):
        with patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await doctor(str(workspace_healthy))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["CI/CD workflow"]["status"] == "pass"

    @pytest.mark.asyncio
    async def test_no_deploy_workflow_warns(self, workspace_with_token):
        write_file(workspace_with_token / ".gitignore", ".env.local\n")
        with patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["CI/CD workflow"]["status"] == "warn"

    @pytest.mark.asyncio
    async def test_perfect_score_single_env(self, workspace_healthy):
        """Single-environment workflow — 6/6."""
        with (
            patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("railguey.lib.doctor._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = {"projectId": "proj-1", "environmentId": "env-1"}
            mock_gql.side_effect = [
                {"project": {
                    "environments": {"edges": [{"node": {"id": "env-1", "name": "production"}}]},
                    "services": {"edges": [{"node": {"id": "svc-1", "name": "web"}}]},
                }},
                {"service": {"id": "svc-1", "name": "web", "repoTriggers": []}},
            ]
            result = await doctor(str(workspace_healthy))
        assert result["score"] == "6/6"
        assert result["healthy"] is True

    @pytest.mark.asyncio
    async def test_perfect_score_multi_env(self, workspace_with_token):
        """Multi-environment workflow with correct token scope — 6/6."""
        write_file(workspace_with_token / ".gitignore", ".env.local\n")
        write_file(
            workspace_with_token / ".github" / "workflows" / "deploy.yml",
            "name: Deploy\n"
            "on:\n"
            "  push:\n"
            "    branches: [main, develop]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: |\n"
            "          railway up --service cerebro --environment production --detach\n"
            "          railway up --service cerebro --environment develop --detach\n"
            "        env:\n"
            "          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n",
        )
        proj_return, gql_calls = _mock_project_and_envs("production")
        with (
            patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("railguey.lib.doctor._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = proj_return
            mock_gql.side_effect = gql_calls
            result = await doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        # Token is scoped to production but workflow targets develop too — should fail
        assert checks["Token environment scope"]["status"] == "fail"
        assert "develop" in checks["Token environment scope"]["message"]

    @pytest.mark.asyncio
    async def test_token_scope_mismatch_fails(self, workspace_with_token):
        """Token scoped to production, workflow targets both — should fail check 5."""
        write_file(workspace_with_token / ".gitignore", ".env.local\n")
        write_file(
            workspace_with_token / ".github" / "workflows" / "deploy.yml",
            "name: Deploy\n"
            "on:\n"
            "  push:\n"
            "    branches: [main, develop]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: |\n"
            "          railway up --service cerebro --environment production --detach\n"
            "          railway up --service cerebro --environment develop --detach\n"
            "        env:\n"
            "          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n",
        )
        proj_return, gql_calls = _mock_project_and_envs("production")
        with (
            patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("railguey.lib.doctor._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = proj_return
            mock_gql.side_effect = gql_calls
            result = await doctor(str(workspace_with_token))

        checks = {f["check"]: f for f in result["findings"]}
        assert checks["Token environment scope"]["status"] == "fail"
        assert "develop" in checks["Token environment scope"]["message"]
        assert "Invalid project token" in checks["Token environment scope"]["message"]

    @pytest.mark.asyncio
    async def test_branch_coverage_mismatch_warns(self, workspace_with_token):
        """Workflow targets 2 envs but only 1 branch triggers — should warn."""
        write_file(workspace_with_token / ".gitignore", ".env.local\n")
        write_file(
            workspace_with_token / ".github" / "workflows" / "deploy.yml",
            "name: Deploy\n"
            "on:\n"
            "  push:\n"
            "    branches: [main]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: |\n"
            "          railway up --service cerebro --environment production --detach\n"
            "          railway up --service cerebro --environment develop --detach\n"
            "        env:\n"
            "          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n",
        )
        with patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj:
            mock_proj.return_value = {"error": "skip"}
            result = await doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["CI/CD workflow"]["status"] == "warn"
        assert "1 branch" in checks["CI/CD workflow"]["message"]
        assert "2 environment" in checks["CI/CD workflow"]["message"]

    @pytest.mark.asyncio
    async def test_invalid_environment_name_fails(self, workspace_with_token):
        """Workflow references an environment that doesn't exist in Railway."""
        write_file(workspace_with_token / ".gitignore", ".env.local\n")
        write_file(
            workspace_with_token / ".github" / "workflows" / "deploy.yml",
            "name: Deploy\n"
            "on:\n"
            "  push:\n"
            "    branches: [main, develop]\n"
            "jobs:\n"
            "  deploy:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: |\n"
            "          railway up --service cerebro --environment production --detach\n"
            "          railway up --service cerebro --environment staging --detach\n"
            "        env:\n"
            "          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}\n",
        )
        proj_return, gql_calls = _mock_project_and_envs("production")
        with (
            patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("railguey.lib.doctor._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = proj_return
            mock_gql.side_effect = gql_calls
            result = await doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["Environment names"]["status"] == "fail"
        assert "staging" in checks["Environment names"]["message"]

    @pytest.mark.asyncio
    async def test_linked_repo_warns(self, workspace_with_token):
        write_file(workspace_with_token / ".gitignore", ".env.local\n")
        with (
            patch("railguey.lib.doctor._resolve_project", new_callable=AsyncMock) as mock_proj,
            patch("railguey.lib.doctor._gql", new_callable=AsyncMock) as mock_gql,
        ):
            mock_proj.return_value = {"projectId": "proj-1", "environmentId": "env-1"}
            mock_gql.side_effect = [
                {"project": {
                    "environments": {"edges": [{"node": {"id": "env-1", "name": "production"}}]},
                    "services": {"edges": [{"node": {"id": "svc-1", "name": "web"}}]},
                }},
                {"service": {"id": "svc-1", "name": "web", "repoTriggers": [{"repository": "org/repo", "branch": "main"}]}},
            ]
            result = await doctor(str(workspace_with_token))
        checks = {f["check"]: f for f in result["findings"]}
        assert checks["GitHub repo linking"]["status"] == "warn"
        assert checks["GitHub repo linking"]["linked"][0]["repo"] == "org/repo"
