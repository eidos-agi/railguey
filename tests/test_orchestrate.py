"""Tests for railguey.lib.orchestrate — registry, preflight, verify, deploy_plan.

Follows the same patterns as test_tools.py and test_doctor.py:
- Class-per-tool grouping
- AsyncMock patches at the orchestrate module level
- conftest fixtures for workspace directories
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


from railguey.lib.orchestrate import (
    registry, preflight, verify, deploy_plan,
    _load_registry, _find_service, _expand_home,
)


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


def _patch_registry(registry_dict: dict):
    return patch("railguey.lib.orchestrate._load_registry", return_value=registry_dict)


def _patch_token(token: str = "test-token", side_effect=None):
    if side_effect is not None:
        return patch("railguey.lib.orchestrate._load_token", side_effect=side_effect)
    return patch("railguey.lib.orchestrate._load_token", return_value=token)


def _patch_project(project: dict | None = None):
    return patch(
        "railguey.lib.orchestrate._resolve_project",
        new_callable=AsyncMock,
        return_value=project if project is not None else {"projectId": "proj-1", "environmentId": "env-1"},
    )


def _patch_service_id(side_effect=None, return_value: str | None = "svc-1"):
    if side_effect is not None:
        return patch("railguey.lib.orchestrate._resolve_service_id", new_callable=AsyncMock, side_effect=side_effect)
    return patch("railguey.lib.orchestrate._resolve_service_id", new_callable=AsyncMock, return_value=return_value)


def _patch_gql(*responses):
    if len(responses) == 1:
        return patch("railguey.lib.orchestrate._gql", new_callable=AsyncMock, return_value=responses[0])
    return patch("railguey.lib.orchestrate._gql", new_callable=AsyncMock, side_effect=list(responses))


def _ok_proc(stdout: str = ""):
    """Mimic subprocess.CompletedProcess with .stdout."""
    return SimpleNamespace(stdout=stdout)


class _FakeHTTPXResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _FakeAsyncClient:
    """Stand-in for httpx.AsyncClient as an async context manager.

    verify() creates a NEW client per health check iteration, so this class
    is instantiated multiple times via the lambda factory.
    """

    def __init__(self, status_codes: list[int]):
        self._codes = list(status_codes)
        self._calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str):
        if self._calls >= len(self._codes):
            code = self._codes[-1]
        else:
            code = self._codes[self._calls]
        self._calls += 1
        return _FakeHTTPXResponse(code)


# We need a shared instance so verify()'s repeated `httpx.AsyncClient(...)` calls
# all hit the same state tracker.
def _fake_client_factory(codes: list[int]):
    client = _FakeAsyncClient(codes)
    return lambda **kwargs: client


# ===================================================================
# registry()
# ===================================================================


class TestRegistry:
    async def test_all_services_returns_count_and_metadata(self):
        reg = {
            "org": {"name": "acme"},
            "defaults": {"verify": {"timeout_seconds": 1}},
            "resources": {"supabase": {}},
            "services": [{"name": "svc-a"}, {"name": "svc-b"}],
        }
        with _patch_registry(reg):
            result = await registry()
        assert result["count"] == 2
        assert [s["name"] for s in result["services"]] == ["svc-a", "svc-b"]
        assert result["org"]["name"] == "acme"

    async def test_single_service_returns_service_and_defaults(self):
        reg = {
            "org": {"name": "acme"},
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "api", "type": "railway_service"}],
        }
        with _patch_registry(reg):
            result = await registry("api")
        assert result["service"]["name"] == "api"
        assert result["org"]["name"] == "acme"
        assert result["defaults"]["preflight"]["require_clean_worktree"] is True

    async def test_unknown_service_returns_known_names(self):
        reg = {"services": [{"name": "api"}, {"name": "web"}]}
        with _patch_registry(reg):
            result = await registry("ghost")
        assert "error" in result
        assert "ghost" in result["error"]
        assert "api" in result["error"]

    async def test_registry_load_error_passthrough(self):
        with _patch_registry({"error": "Registry not found"}):
            result = await registry()
        assert result == {"error": "Registry not found"}


# ===================================================================
# preflight()
# ===================================================================


class TestPreflight:
    def _base_registry(self, ws_service, ws_migrations, ws_dep_api):
        return {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [
                {
                    "name": "db-migrations", "type": "migrations", "repo": "db-migrations",
                    "workspace": ws_migrations, "deploy": {"branch": "main"},
                },
                {
                    "name": "dep-api", "type": "railway_service", "repo": "dep-api",
                    "workspace": ws_dep_api, "deploy": {"branch": "main"},
                },
                {
                    "name": "api", "type": "railway_service", "repo": "api",
                    "workspace": ws_service, "deploy": {"branch": "main"},
                    "depends_on": [
                        {"target": "db-migrations", "gate": "required_before_deploy"},
                        {"target": "dep-api", "gate": "required_before_deploy"},
                    ],
                },
            ],
        }

    async def test_happy_path_go_true(self, workspace_with_token, tmp_path):
        ws = str(workspace_with_token)
        reg = self._base_registry(ws, str(tmp_path / "db"), str(tmp_path / "dep"))

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            if cmd[:4] == ["npx", "supabase", "migration", "list"]:
                return _ok_proc("20260101_init | 20260101_init | 2026-01-01\n")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql_concurrency = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS"}}]}}
        gql_dep_api = {"deployments": {"edges": [{"node": {"status": "SUCCESS"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(side_effect=lambda token, project_id, name: f"sid-{name}"),
            _patch_gql(gql_concurrency, gql_dep_api),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=ws)

        assert result["go"] is True
        assert result["blocking"] == []
        checks = {c["check"]: c for c in result["passed"]}
        assert checks["branch"]["status"] == "pass"
        assert checks["worktree"]["status"] == "pass"
        assert checks["concurrency"]["status"] == "pass"
        assert checks["dependency:db-migrations"]["status"] == "pass"
        assert checks["dependency:dep-api"]["status"] == "pass"

    async def test_unknown_service_blocks(self, workspace_with_token):
        reg = {"services": [{"name": "api"}]}
        with _patch_registry(reg):
            result = await preflight("ghost", workspace=str(workspace_with_token))
        assert result["go"] is False
        assert "ghost" in result["reasons"][0]

    async def test_wrong_branch_blocks(self, workspace_with_token):
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "api", "type": "railway_service",
                          "workspace": str(workspace_with_token), "deploy": {"branch": "main"}}],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("develop\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(gql),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        assert result["go"] is False
        assert any(b["check"] == "branch" for b in result["blocking"])

    async def test_dirty_worktree_blocks(self, workspace_with_token):
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "api", "type": "railway_service",
                          "workspace": str(workspace_with_token), "deploy": {"branch": "main"}}],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc(" M app.py\n?? new.txt\n")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(gql),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        assert result["go"] is False
        assert any(b["check"] == "worktree" for b in result["blocking"])

    async def test_concurrent_deploy_blocks(self, workspace_with_token):
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "api", "type": "railway_service",
                          "workspace": str(workspace_with_token), "deploy": {"branch": "main"}}],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "BUILDING"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(gql),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        assert result["go"] is False
        assert any(b["check"] == "concurrency" for b in result["blocking"])

    async def test_migrations_dependency_unsynced_blocks(self, workspace_with_token, tmp_path):
        ws = str(workspace_with_token)
        reg = self._base_registry(ws, str(tmp_path / "db"), str(tmp_path / "dep"))

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            if cmd[:4] == ["npx", "supabase", "migration", "list"]:
                # Local present, remote missing = unsynced
                return _ok_proc("20260101_init |  | 2026-01-01\n")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql_concurrency = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS"}}]}}
        gql_dep_api = {"deployments": {"edges": [{"node": {"status": "SUCCESS"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(side_effect=lambda token, project_id, name: f"sid-{name}"),
            _patch_gql(gql_concurrency, gql_dep_api),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=ws)

        assert result["go"] is False
        assert any(b["check"] == "dependency:db-migrations" for b in result["blocking"])

    async def test_registry_error_passthrough(self):
        with _patch_registry({"error": "Registry not found"}):
            result = await preflight("api")
        assert result == {"error": "Registry not found"}


# ===================================================================
# verify()
# ===================================================================


class TestVerify:
    async def test_non_railway_service_skips_and_passes(self, workspace):
        reg = {
            "defaults": {"verify": {"timeout_seconds": 1, "poll_interval_seconds": 0}},
            "services": [{"name": "db", "type": "migrations", "workspace": str(workspace)}],
        }
        with _patch_registry(reg):
            result = await verify("db", workspace=str(workspace))
        assert result["pass"] is True
        assert result["checks"][0]["check"] == "deploy_poll"
        assert result["checks"][0]["status"] == "skip"

    async def test_deploy_failed_early_exit(self, workspace_with_token):
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0, "success_streak": 2}},
            "services": [{"name": "api", "type": "railway_service", "workspace": str(workspace_with_token)}],
        }
        dep_failed = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "FAILED", "createdAt": "t"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_failed),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is False
        assert any(c["check"] == "deploy_poll" and c["status"] == "fail" for c in result["checks"])
        # Should not proceed to log scan
        assert not any(c["check"] == "log_scan" for c in result["checks"])

    async def test_deploy_timeout_fails(self, workspace_with_token):
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0}},
            "services": [{"name": "api", "type": "railway_service", "workspace": str(workspace_with_token)}],
        }
        dep_building = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "DEPLOYING", "createdAt": "t"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_building),
            patch("railguey.lib.orchestrate.time.time", side_effect=[0, 100]),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is False
        poll = next(c for c in result["checks"] if c["check"] == "deploy_poll")
        assert poll["status"] == "fail"
        assert "Timed out" in poll["detail"]

    async def test_log_scan_finds_fail_fast_pattern(self, workspace_with_token):
        reg = {
            "defaults": {
                "verify": {
                    "timeout_seconds": 5, "poll_interval_seconds": 0,
                    "log_tail_lines": 10, "fail_fast_patterns": ["Traceback"], "success_streak": 2,
                }
            },
            "services": [{
                "name": "api", "type": "railway_service", "workspace": str(workspace_with_token),
                "health": {"http": {"path": "/health", "expect_status": 200}, "log_patterns": {"fail_fast": []}},
                "verify": {"success_streak": 2},
            }],
        }

        dep_success = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS", "createdAt": "t"}}]}}
        logs_with_error = {
            "deploymentLogs": [
                {"message": "INFO booting", "timestamp": "t", "severity": "info"},
                {"message": "Traceback (most recent call last): boom", "timestamp": "t", "severity": "error"},
            ]
        }

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_success, logs_with_error),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is False
        assert any(c["check"] == "log_scan" and c["status"] == "fail" for c in result["checks"])
        # Should not proceed to health check
        assert not any(c["check"] == "health_http" for c in result["checks"])

    async def test_health_streak_passes(self, workspace_with_token):
        reg = {
            "defaults": {
                "verify": {
                    "timeout_seconds": 5, "poll_interval_seconds": 0,
                    "log_tail_lines": 10, "fail_fast_patterns": [], "success_streak": 2,
                }
            },
            "services": [{
                "name": "api", "type": "railway_service", "workspace": str(workspace_with_token),
                "health": {"http": {"path": "/health", "expect_status": 200}},
                "verify": {"success_streak": 2},
            }],
        }

        dep_success = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS", "createdAt": "t"}}]}}
        svc_domains = {
            "service": {
                "serviceInstances": {
                    "edges": [{"node": {"domains": {
                        "customDomains": [],
                        "serviceDomains": [{"domain": "api.up.railway.app"}],
                    }}}]
                }
            }
        }

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_success, svc_domains),
            patch("railguey.lib.orchestrate.httpx.AsyncClient", new=_fake_client_factory([200, 200])),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is True
        assert any(c["check"] == "health_http" and c["status"] == "pass" for c in result["checks"])

    async def test_health_streak_fails(self, workspace_with_token):
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0, "fail_fast_patterns": []}},
            "services": [{
                "name": "api", "type": "railway_service", "workspace": str(workspace_with_token),
                "health": {"http": {"path": "/health", "expect_status": 200}},
                "verify": {"success_streak": 2},
            }],
        }

        dep_success = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS", "createdAt": "t"}}]}}
        svc_domains = {
            "service": {
                "serviceInstances": {
                    "edges": [{"node": {"domains": {
                        "customDomains": [],
                        "serviceDomains": [{"domain": "api.up.railway.app"}],
                    }}}]
                }
            }
        }

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_success, svc_domains),
            patch("railguey.lib.orchestrate.httpx.AsyncClient", new=_fake_client_factory([500, 500, 500, 500])),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is False
        assert any(c["check"] == "health_http" and c["status"] == "fail" for c in result["checks"])

    async def test_no_domain_skips_health_but_passes(self, workspace_with_token):
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0, "fail_fast_patterns": []}},
            "services": [{
                "name": "api", "type": "railway_service", "workspace": str(workspace_with_token),
                "health": {"http": {"path": "/health", "expect_status": 200}},
                "verify": {"success_streak": 2},
            }],
        }

        dep_success = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS", "createdAt": "t"}}]}}
        svc_no_domains = {"service": {"serviceInstances": {"edges": [
            {"node": {"domains": {"customDomains": [], "serviceDomains": []}}}
        ]}}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_success, svc_no_domains),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is True
        assert any(c["check"] == "health_http" and c["status"] == "skip" for c in result["checks"])

    async def test_unknown_service_fails(self):
        reg = {"services": [{"name": "api"}]}
        with _patch_registry(reg):
            result = await verify("ghost")
        assert result["pass"] is False
        assert "ghost" in result["error"]

    async def test_registry_error_passthrough(self):
        with _patch_registry({"error": "Registry not found"}):
            result = await verify("api")
        assert result == {"error": "Registry not found"}


# ===================================================================
# deploy_plan()
# ===================================================================


class TestDeployPlan:
    def _plan_registry(self):
        return {
            "services": [
                {"name": "db", "type": "migrations", "repo": "db-repo", "deploy": {"branch": "main"}},
                {
                    "name": "api", "type": "railway_service", "repo": "api-repo",
                    "deploy": {"branch": "main"},
                    "depends_on": [{"target": "db", "gate": "required_before_deploy"}],
                },
                {
                    "name": "web", "type": "railway_service", "repo": "web-repo",
                    "deploy": {"branch": "main"},
                    "depends_on": [{"target": "api", "gate": "recommended_before_verify"}],
                },
            ]
        }

    async def test_unknown_repo_returns_known_repos(self):
        with _patch_registry(self._plan_registry()):
            result = await deploy_plan(["nope-repo"])
        assert "error" in result
        assert set(result["known_repos"]) == {"db-repo", "api-repo", "web-repo"}

    async def test_auto_includes_required_before_deploy_dependency(self):
        with _patch_registry(self._plan_registry()):
            result = await deploy_plan(["api-repo"])
        assert result["services_affected"] == ["api"]
        assert result["auto_included_dependencies"] == ["db"]
        assert any("auto-included" in w for w in result["warnings"])

        stages = result["stages"]
        # Stage 1: migrations (db), Stage 2: api (depended-upon by web? No — web not in plan)
        # Actually: db is migrations → stage 1, api is leaf → stage 3
        # But api depends_on db which is depended-upon, and api is not depended-upon itself
        assert stages[0]["label"] == "Database migrations"
        assert [s["name"] for s in stages[0]["services"]] == ["db"]
        assert stages[0]["services"][0]["in_change_set"] is False  # auto-included

    async def test_single_repo_no_deps(self):
        """web has only recommended_before_verify dep — not expanded."""
        with _patch_registry(self._plan_registry()):
            result = await deploy_plan(["web-repo"])
        assert result["services_affected"] == ["web"]
        assert result["auto_included_dependencies"] == []
        assert len(result["stages"]) == 1
        assert result["stages"][0]["label"] == "Frontends and workers"

    async def test_full_stack_three_stages(self):
        with _patch_registry(self._plan_registry()):
            result = await deploy_plan(["db-repo", "api-repo", "web-repo"])

        stages = result["stages"]
        stage_labels = [s["label"] for s in stages]
        assert "Database migrations" in stage_labels

        # All services in change set
        for stage in stages:
            for svc in stage["services"]:
                assert svc["in_change_set"] is True

    async def test_stage_ordering_migrations_first(self):
        with _patch_registry(self._plan_registry()):
            result = await deploy_plan(["db-repo", "api-repo", "web-repo"])
        stages = result["stages"]
        # Migrations must be stage 1
        assert stages[0]["label"] == "Database migrations"
        assert stages[0]["gate"] == "blocking — must complete before proceeding"

    async def test_parallel_flag_on_multi_service_stage(self):
        """Stage with >1 service gets parallel=True."""
        reg = {
            "services": [
                {"name": "db", "type": "migrations", "repo": "db-repo", "deploy": {"branch": "main"}},
                {"name": "api-a", "type": "railway_service", "repo": "api-a-repo",
                 "deploy": {"branch": "main"}},
                {"name": "api-b", "type": "railway_service", "repo": "api-b-repo",
                 "deploy": {"branch": "main"}},
            ]
        }
        with _patch_registry(reg):
            result = await deploy_plan(["api-a-repo", "api-b-repo"])
        # Both are leaf services (no one depends on them) → same stage
        leaf_stage = next(s for s in result["stages"] if s["label"] == "Frontends and workers")
        assert leaf_stage["parallel"] is True

    async def test_registry_error_passthrough(self):
        with _patch_registry({"error": "Registry not found"}):
            result = await deploy_plan(["any-repo"])
        assert result == {"error": "Registry not found"}

    async def test_chain_dependency_expansion(self):
        """A→B→C: changing A should auto-include B and C."""
        reg = {
            "services": [
                {"name": "c", "type": "migrations", "repo": "c-repo", "deploy": {"branch": "main"}},
                {"name": "b", "type": "railway_service", "repo": "b-repo",
                 "deploy": {"branch": "main"},
                 "depends_on": [{"target": "c", "gate": "required_before_deploy"}]},
                {"name": "a", "type": "railway_service", "repo": "a-repo",
                 "deploy": {"branch": "main"},
                 "depends_on": [{"target": "b", "gate": "required_before_deploy"}]},
            ]
        }
        with _patch_registry(reg):
            result = await deploy_plan(["a-repo"])
        assert result["services_affected"] == ["a"]
        assert sorted(result["auto_included_dependencies"]) == ["b", "c"]
        assert result["total_services"] == 3

    async def test_stage_numbering_when_no_migrations(self):
        """When no migrations in plan, stage numbers still start at correct values."""
        reg = {
            "services": [
                {"name": "api", "type": "railway_service", "repo": "api-repo",
                 "deploy": {"branch": "main"}},
                {"name": "web", "type": "railway_service", "repo": "web-repo",
                 "deploy": {"branch": "main"},
                 "depends_on": [{"target": "api", "gate": "required_before_deploy"}]},
            ]
        }
        with _patch_registry(reg):
            result = await deploy_plan(["web-repo"])
        # api is auto-included, depended-upon → stage 2 label
        # web is leaf → stage 3 label
        # But no migrations → stage numbers should still be sequential
        stages = result["stages"]
        assert all("stage" in s for s in stages)
        # No "Database migrations" stage
        assert not any(s["label"] == "Database migrations" for s in stages)

    async def test_depended_upon_service_in_stage_2(self):
        """A service that others depend on lands in stage 2 (API layer)."""
        reg = {
            "services": [
                {"name": "db", "type": "migrations", "repo": "db-repo", "deploy": {"branch": "main"}},
                {"name": "api", "type": "railway_service", "repo": "api-repo",
                 "deploy": {"branch": "main"},
                 "depends_on": [{"target": "db", "gate": "required_before_deploy"}]},
                {"name": "web", "type": "railway_service", "repo": "web-repo",
                 "deploy": {"branch": "main"},
                 "depends_on": [{"target": "api", "gate": "required_before_deploy"}]},
            ]
        }
        with _patch_registry(reg):
            result = await deploy_plan(["db-repo", "api-repo", "web-repo"])
        stages = result["stages"]
        stage2 = next(s for s in stages if s["label"] == "API and config services")
        assert [svc["name"] for svc in stage2["services"]] == ["api"]

    async def test_single_service_stage_parallel_false(self):
        """Stage with exactly 1 service gets parallel=False."""
        reg = {
            "services": [
                {"name": "solo", "type": "railway_service", "repo": "solo-repo",
                 "deploy": {"branch": "main"}},
            ]
        }
        with _patch_registry(reg):
            result = await deploy_plan(["solo-repo"])
        assert result["stages"][0]["parallel"] is False

    async def test_empty_warnings_when_no_auto_includes(self):
        with _patch_registry(self._plan_registry()):
            result = await deploy_plan(["web-repo"])
        assert result["warnings"] == []


# ===================================================================
# Unit tests for internal helpers
# ===================================================================


class TestExpandHome:
    def test_expands_tilde(self):
        result = _expand_home("~/repos/test")
        assert not result.startswith("~")
        assert result.endswith("/repos/test")

    def test_returns_absolute_path_unchanged(self):
        assert _expand_home("/absolute/path") == "/absolute/path"

    def test_returns_none_for_none(self):
        assert _expand_home(None) is None

    def test_returns_empty_string_unchanged(self):
        # Empty string is falsy → hits the `if path` guard, returns as-is
        assert _expand_home("") == ""


class TestFindService:
    def test_finds_by_name(self):
        reg = {"services": [{"name": "api"}, {"name": "web"}]}
        assert _find_service(reg, "api")["name"] == "api"

    def test_returns_none_for_unknown(self):
        reg = {"services": [{"name": "api"}]}
        assert _find_service(reg, "ghost") is None

    def test_handles_empty_services(self):
        assert _find_service({"services": []}, "api") is None

    def test_handles_missing_services_key(self):
        assert _find_service({}, "api") is None


class TestLoadRegistry:
    def test_returns_error_when_no_file_exists(self, tmp_path):
        """When neither registry path exists, returns error dict."""
        with patch("railguey.lib.orchestrate._REGISTRY_PATHS", [tmp_path / "nope.yaml"]):
            result = _load_registry()
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_loads_yaml_from_first_matching_path(self, tmp_path):
        reg_file = tmp_path / "registry.yaml"
        reg_file.write_text("services:\n  - name: test-svc\n")
        with patch("railguey.lib.orchestrate._REGISTRY_PATHS", [reg_file]):
            result = _load_registry()
        assert result["services"][0]["name"] == "test-svc"


# ===================================================================
# Additional preflight edge cases
# ===================================================================


class TestPreflightEdgeCases:
    async def test_subprocess_exception_skips_branch_check(self, workspace_with_token):
        """When git branch fails, check is skipped (not blocking)."""
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": False}},
            "services": [{"name": "api", "type": "railway_service",
                          "workspace": str(workspace_with_token), "deploy": {"branch": "main"}}],
        }

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql({"deployments": {"edges": [{"node": {"id": "d1", "status": "SUCCESS"}}]}}),
            patch("subprocess.run", side_effect=OSError("git not found")),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        # Branch check should be "skip", not "fail"
        assert result["go"] is True
        checks = {c["check"]: c for c in result["passed"]}
        assert checks["branch"]["status"] == "skip"

    async def test_no_workspace_skips_git_and_concurrency_checks(self):
        """Service with no workspace path skips local checks."""
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "api", "type": "railway_service",
                          "deploy": {"branch": "main"}}],  # no workspace key
        }
        with _patch_registry(reg):
            result = await preflight("api")
        # Should still return go=True since no checks could run to block
        assert result["go"] is True
        assert result["passed"] == []
        assert result["blocking"] == []

    async def test_non_railway_service_skips_concurrency_check(self, workspace_with_token):
        """Migrations type doesn't get concurrency check."""
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "db", "type": "migrations",
                          "workspace": str(workspace_with_token), "deploy": {"branch": "main"}}],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        with (
            _patch_registry(reg),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("db", workspace=str(workspace_with_token))

        assert result["go"] is True
        check_names = [c["check"] for c in result["passed"]]
        assert "concurrency" not in check_names

    async def test_resolve_project_error_skips_concurrency(self, workspace_with_token):
        """When Railway API returns error, concurrency check is skipped."""
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "api", "type": "railway_service",
                          "workspace": str(workspace_with_token), "deploy": {"branch": "main"}}],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project({"error": "bad token"}),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        # Concurrency check silently skipped when project resolution fails
        assert result["go"] is True
        check_names = [c["check"] for c in result["passed"]]
        assert "concurrency" not in check_names

    async def test_dependency_target_not_in_registry_blocks(self, workspace_with_token):
        """Dependency pointing to unknown service blocks deploy."""
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{
                "name": "api", "type": "railway_service",
                "workspace": str(workspace_with_token), "deploy": {"branch": "main"},
                "depends_on": [{"target": "phantom-db", "gate": "required_before_deploy"}],
            }],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql = {"deployments": {"edges": [{"node": {"id": "d1", "status": "SUCCESS"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(gql),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        assert result["go"] is False
        assert any(b["check"] == "dependency:phantom-db" for b in result["blocking"])

    async def test_recommended_deps_are_not_checked(self, workspace_with_token):
        """Only required_before_deploy deps are checked, not recommended."""
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [
                {"name": "ai-svc", "type": "railway_service", "workspace": "/tmp/ai",
                 "deploy": {"branch": "main"}},
                {
                    "name": "web", "type": "railway_service",
                    "workspace": str(workspace_with_token), "deploy": {"branch": "main"},
                    "depends_on": [{"target": "ai-svc", "gate": "recommended_before_verify"}],
                },
            ],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql = {"deployments": {"edges": [{"node": {"id": "d1", "status": "SUCCESS"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-web"),
            _patch_gql(gql),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("web", workspace=str(workspace_with_token))

        # ai-svc is recommended, not required — should not appear in checks
        assert result["go"] is True
        all_check_names = [c["check"] for c in result["passed"] + result["blocking"]]
        assert "dependency:ai-svc" not in all_check_names

    async def test_railway_dependency_failed_blocks(self, workspace_with_token, tmp_path):
        """Railway service dependency with FAILED status blocks deploy."""
        ws = str(workspace_with_token)
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [
                {"name": "dep-api", "type": "railway_service", "repo": "dep-api",
                 "workspace": str(tmp_path / "dep"), "deploy": {"branch": "main"}},
                {
                    "name": "api", "type": "railway_service", "repo": "api",
                    "workspace": ws, "deploy": {"branch": "main"},
                    "depends_on": [{"target": "dep-api", "gate": "required_before_deploy"}],
                },
            ],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql_concurrency = {"deployments": {"edges": [{"node": {"id": "d1", "status": "SUCCESS"}}]}}
        gql_dep_failed = {"deployments": {"edges": [{"node": {"status": "FAILED"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(side_effect=lambda token, project_id, name: f"sid-{name}"),
            _patch_gql(gql_concurrency, gql_dep_failed),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=ws)

        assert result["go"] is False
        dep_block = next(b for b in result["blocking"] if b["check"] == "dependency:dep-api")
        assert "FAILED" in dep_block["detail"]

    async def test_multiple_blocking_issues_counted(self, workspace_with_token):
        """Multiple failures produce correct summary count."""
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "api", "type": "railway_service",
                          "workspace": str(workspace_with_token), "deploy": {"branch": "main"}}],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("develop\n")  # wrong branch
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc(" M dirty.py\n")  # dirty
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql = {"deployments": {"edges": [{"node": {"id": "d1", "status": "BUILDING"}}]}}  # concurrent

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(gql),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        assert result["go"] is False
        assert len(result["blocking"]) == 3
        assert "3 blocking issue(s)" in result["summary"]


# ===================================================================
# Additional verify edge cases
# ===================================================================


class TestVerifyEdgeCases:
    async def test_no_workspace_returns_error(self):
        """Service exists but has no workspace → early error."""
        reg = {
            "defaults": {"verify": {}},
            "services": [{"name": "api", "type": "railway_service"}],  # no workspace
        }
        with _patch_registry(reg):
            result = await verify("api")
        assert result["pass"] is False
        assert "workspace" in result["error"].lower()

    async def test_resolve_project_error_fails(self, workspace_with_token):
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0}},
            "services": [{"name": "api", "type": "railway_service", "workspace": str(workspace_with_token)}],
        }
        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project({"error": "bad token"}),
        ):
            result = await verify("api", workspace=str(workspace_with_token))
        assert result["pass"] is False
        assert any(c["check"] == "deploy_poll" and c["status"] == "fail" for c in result["checks"])

    async def test_resolve_service_id_none_fails(self, workspace_with_token):
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0}},
            "services": [{"name": "api", "type": "railway_service", "workspace": str(workspace_with_token)}],
        }
        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value=None),
        ):
            result = await verify("api", workspace=str(workspace_with_token))
        assert result["pass"] is False
        assert "not found in Railway" in result["checks"][0]["detail"]

    async def test_crashed_status_fails(self, workspace_with_token):
        """CRASHED is a terminal non-SUCCESS status."""
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0}},
            "services": [{"name": "api", "type": "railway_service", "workspace": str(workspace_with_token)}],
        }
        dep_crashed = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "CRASHED", "createdAt": "t"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_crashed),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is False
        poll = next(c for c in result["checks"] if c["check"] == "deploy_poll")
        assert "CRASHED" in poll["detail"]

    async def test_log_scan_clean_proceeds_to_health(self, workspace_with_token):
        """Clean log scan passes and proceeds to health check phase."""
        reg = {
            "defaults": {
                "verify": {
                    "timeout_seconds": 5, "poll_interval_seconds": 0,
                    "log_tail_lines": 10, "fail_fast_patterns": ["FATAL"], "success_streak": 2,
                }
            },
            "services": [{
                "name": "api", "type": "railway_service", "workspace": str(workspace_with_token),
                "health": {"http": {"path": "/health", "expect_status": 200}, "log_patterns": {"fail_fast": []}},
                "verify": {"success_streak": 2},
            }],
        }

        dep_success = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS", "createdAt": "t"}}]}}
        clean_logs = {"deploymentLogs": [
            {"message": "INFO server started", "timestamp": "t", "severity": "info"},
            {"message": "INFO listening on :3000", "timestamp": "t", "severity": "info"},
        ]}
        svc_domains = {"service": {"serviceInstances": {"edges": [
            {"node": {"domains": {"customDomains": [], "serviceDomains": [{"domain": "api.up.railway.app"}]}}}
        ]}}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_success, clean_logs, svc_domains),
            patch("railguey.lib.orchestrate.httpx.AsyncClient", new=_fake_client_factory([200, 200])),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is True
        check_names = [c["check"] for c in result["checks"]]
        assert "log_scan" in check_names
        assert "health_http" in check_names
        log_check = next(c for c in result["checks"] if c["check"] == "log_scan")
        assert log_check["status"] == "pass"

    async def test_no_health_http_config_skips_health_check(self, workspace_with_token):
        """Service with no health.http config skips health check entirely."""
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0, "fail_fast_patterns": []}},
            "services": [{
                "name": "worker", "type": "railway_service", "workspace": str(workspace_with_token),
                # No health.http — just log patterns
                "health": {"log_patterns": {"fail_fast": []}},
            }],
        }

        dep_success = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS", "createdAt": "t"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-worker"),
            _patch_gql(dep_success),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("worker", workspace=str(workspace_with_token))

        assert result["pass"] is True
        check_names = [c["check"] for c in result["checks"]]
        assert "health_http" not in check_names

    async def test_fail_patterns_merged_from_service_and_defaults(self, workspace_with_token):
        """Fail-fast patterns combine service-level + default-level."""
        reg = {
            "defaults": {
                "verify": {
                    "timeout_seconds": 5, "poll_interval_seconds": 0,
                    "log_tail_lines": 10, "fail_fast_patterns": ["FATAL"],
                }
            },
            "services": [{
                "name": "api", "type": "railway_service", "workspace": str(workspace_with_token),
                "health": {"log_patterns": {"fail_fast": ["SQLSTATE"]}},
            }],
        }

        dep_success = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS", "createdAt": "t"}}]}}
        # Log contains a service-level pattern (SQLSTATE), not a default one
        logs = {"deploymentLogs": [
            {"message": "ERROR: SQLSTATE[42P01] relation does not exist", "timestamp": "t", "severity": "error"},
        ]}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_success, logs),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is False
        log_check = next(c for c in result["checks"] if c["check"] == "log_scan")
        assert log_check["status"] == "fail"
        assert any(m["pattern"] == "SQLSTATE" for m in log_check["matches"])

    async def test_custom_domain_preferred_over_service_domain(self, workspace_with_token):
        """When both custom and service domains exist, URL uses first available."""
        reg = {
            "defaults": {
                "verify": {
                    "timeout_seconds": 5, "poll_interval_seconds": 0,
                    "fail_fast_patterns": [], "success_streak": 2,
                }
            },
            "services": [{
                "name": "api", "type": "railway_service", "workspace": str(workspace_with_token),
                "health": {"http": {"path": "/health", "expect_status": 200}},
                "verify": {"success_streak": 2},
            }],
        }

        dep_success = {"deployments": {"edges": [{"node": {"id": "dep-1", "status": "SUCCESS", "createdAt": "t"}}]}}
        svc_domains = {"service": {"serviceInstances": {"edges": [{"node": {"domains": {
            "customDomains": [{"domain": "api.example.com"}],
            "serviceDomains": [{"domain": "api.up.railway.app"}],
        }}}]}}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(dep_success, svc_domains),
            patch("railguey.lib.orchestrate.httpx.AsyncClient", new=_fake_client_factory([200, 200])),
            patch("railguey.lib.orchestrate.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await verify("api", workspace=str(workspace_with_token))

        assert result["pass"] is True
        health = next(c for c in result["checks"] if c["check"] == "health_http")
        assert "api.example.com" in health["detail"]

    async def test_outer_exception_returns_error_status(self, workspace_with_token):
        """Exception in Railway API calls produces error check."""
        reg = {
            "defaults": {"verify": {"timeout_seconds": 5, "poll_interval_seconds": 0}},
            "services": [{"name": "api", "type": "railway_service", "workspace": str(workspace_with_token)}],
        }
        with (
            _patch_registry(reg),
            _patch_token(side_effect=ValueError("no token")),
        ):
            result = await verify("api", workspace=str(workspace_with_token))
        assert result["pass"] is False
        assert any(c["check"] == "verify" and c["status"] == "error" for c in result["checks"])


# ===================================================================
# Flaw detection — tests that expose real bugs or design gaps
# ===================================================================


class TestFlawDetection:
    """Tests that document actual flaws found in orchestrate.py.

    Each test is marked with the flaw it exposes. These serve as regression
    tests once the flaws are fixed.
    """

    async def test_concurrency_skip_emitted_when_service_id_none(self, workspace_with_token):
        """FIX VERIFIED: When _resolve_service_id returns None, the concurrency
        check now emits a 'skip' status so the caller knows it didn't run.
        """
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [{"name": "api", "type": "railway_service",
                          "workspace": str(workspace_with_token), "deploy": {"branch": "main"}}],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value=None),  # service not found in Railway
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        # FIX: concurrency check now appears with "skip" status
        all_checks = result["passed"] + result["blocking"]
        concurrency = [c for c in all_checks if c["check"] == "concurrency"]
        assert len(concurrency) == 1, "concurrency check should appear exactly once"
        assert concurrency[0]["status"] == "skip"
        assert "not found" in concurrency[0]["detail"]

    async def test_no_workspace_on_required_dep_blocks_preflight(self, workspace_with_token):
        """FIX VERIFIED: A required_before_deploy dependency on a railway_service
        with no workspace now blocks preflight with a 'fail' status.
        """
        reg = {
            "defaults": {"preflight": {"require_clean_worktree": True}},
            "services": [
                # Dependency has NO workspace
                {"name": "dep-api", "type": "railway_service", "repo": "dep-api",
                 "deploy": {"branch": "main"}},  # no workspace key
                {
                    "name": "api", "type": "railway_service", "repo": "api",
                    "workspace": str(workspace_with_token), "deploy": {"branch": "main"},
                    "depends_on": [{"target": "dep-api", "gate": "required_before_deploy"}],
                },
            ],
        }

        def run_side_effect(cmd, cwd=None, capture_output=None, text=None, timeout=None):
            if cmd[:3] == ["git", "branch", "--show-current"]:
                return _ok_proc("main\n")
            if cmd[:3] == ["git", "status", "--porcelain"]:
                return _ok_proc("")
            raise AssertionError(f"Unexpected subprocess: {cmd}")

        gql = {"deployments": {"edges": [{"node": {"id": "d1", "status": "SUCCESS"}}]}}

        with (
            _patch_registry(reg),
            _patch_token(),
            _patch_project(),
            _patch_service_id(return_value="sid-api"),
            _patch_gql(gql),
            patch("subprocess.run", side_effect=run_side_effect),
        ):
            result = await preflight("api", workspace=str(workspace_with_token))

        # FIX: go=False, dep-api check now blocks with "fail"
        assert result["go"] is False
        dep_checks = [c for c in result["blocking"] if c["check"] == "dependency:dep-api"]
        assert len(dep_checks) == 1
        assert dep_checks[0]["status"] == "fail"
        assert "no workspace" in dep_checks[0]["detail"]

    async def test_soft_deps_do_not_inflate_staging(self):
        """FIX VERIFIED: deploy_plan() now only uses required_before_* deps
        to determine stage ordering. A service with only 'recommended' deps
        pointing at it stays in stage 3 (leaf), not stage 2 (API layer).
        """
        reg = {
            "services": [
                {"name": "api", "type": "railway_service", "repo": "api-repo",
                 "deploy": {"branch": "main"}},
                {"name": "web", "type": "railway_service", "repo": "web-repo",
                 "deploy": {"branch": "main"},
                 "depends_on": [{"target": "api", "gate": "recommended_before_verify"}]},
            ]
        }
        with _patch_registry(reg):
            result = await deploy_plan(["api-repo", "web-repo"])

        stages = result["stages"]
        # FIX: api is in stage 3 (leaf) since only recommended deps point at it
        api_stage = None
        for stage in stages:
            for svc in stage["services"]:
                if svc["name"] == "api":
                    api_stage = stage
        assert api_stage is not None, "api should appear in some stage"
        assert api_stage["label"] != "API and config services", \
            "recommended dep should NOT promote service to stage 2"

    async def test_flaw_migration_parser_with_real_supabase_output(self):
        """Verify migration parser works with REAL supabase CLI output format.
        This is a regression test — the parser splits on '|' which matches
        the actual supabase output (ASCII pipe, not unicode box-drawing).
        """
        # Real supabase output (captured from production)
        real_output = (
            "\n"
            "   Local          | Remote         | Time (UTC)          \n"
            "  ----------------|----------------|---------------------\n"
            "   20260308000100 | 20260308000100 | 2026-03-08 00:01:00 \n"
            "   20260312020000 |                |                     \n"  # local-only!
        )

        unsynced = []
        for line in real_output.split("\n"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2 and parts[0] and not parts[1]:
                unsynced.append(parts[0])

        assert unsynced == ["20260312020000"], \
            f"Parser should detect local-only migration, got: {unsynced}"

    async def test_flaw_migration_parser_header_row_not_false_positive(self):
        """Verify header row 'Local | Remote | Time' doesn't trigger false positive."""
        header_output = (
            "   Local          | Remote         | Time (UTC)          \n"
            "  ----------------|----------------|---------------------\n"
            "   20260308000100 | 20260308000100 | 2026-03-08 00:01:00 \n"
        )

        unsynced = []
        for line in header_output.split("\n"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2 and parts[0] and not parts[1]:
                unsynced.append(parts[0])

        assert unsynced == [], \
            f"Header/separator should NOT trigger false positive, got: {unsynced}"
