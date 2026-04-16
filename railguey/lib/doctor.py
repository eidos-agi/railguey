"""Opinionated workspace audit for Railway deployment best practices.

Three-layer architecture:
  - doctor():                   workspace fundamentals + calls both sub-doctors
  - doctor_service_level():     this service only (deploy health, domain, drift)
  - doctor_project_level():     whole project (all services, cross-service issues)
"""

from pathlib import Path

import yaml

from railguey.lib.token import _load_token
from railguey.lib.graphql import _gql, _resolve_project


# --- Workflow templates (embedded so doctor can prescribe without external reads) ---

_WORKFLOW_TEMPLATE = """\
name: Deploy to Railway

on:
  push:
    branches: [{branch}]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Railway CLI
        run: npm install -g @railway/cli

      - name: Deploy
        env:
          RAILWAY_TOKEN: ${{{{ secrets.RAILWAY_TOKEN }}}}
          RAILWAY_SERVICE: ${{{{ vars.RAILWAY_SERVICE }}}}
          RAILWAY_ENVIRONMENT: ${{{{ vars.RAILWAY_ENVIRONMENT }}}}
        run: railway up --service "$RAILWAY_SERVICE" --environment "$RAILWAY_ENVIRONMENT" --detach
"""


def _parse_workflow_details(workflows_dir: Path) -> dict:
    """Parse deploy workflow(s) for Railway-specific details."""
    result = {
        "found": False,
        "branches": [],
        "environments": [],
        "services": [],
        "file": "",
    }
    if not workflows_dir.is_dir():
        return result

    for f in workflows_dir.iterdir():
        if f.suffix not in (".yml", ".yaml") or not f.is_file():
            continue
        content = f.read_text()
        if "railway" not in content.lower() or "RAILWAY_TOKEN" not in content:
            continue

        result["found"] = True
        result["file"] = f.name

        try:
            parsed = yaml.safe_load(content)
            if isinstance(parsed, dict):
                on = parsed.get("on") or parsed.get(True) or {}
                if isinstance(on, dict):
                    push = on.get("push", {})
                    if isinstance(push, dict):
                        branches = push.get("branches", [])
                        if isinstance(branches, list):
                            result["branches"] = [str(b) for b in branches]
        except Exception:
            pass

        for line in content.splitlines():
            stripped = line.strip()
            if "--environment" in stripped:
                for part in stripped.split():
                    if part.startswith("--environment="):
                        result["environments"].append(part.split("=", 1)[1])
                    elif part == "--environment":
                        idx = stripped.split().index("--environment")
                        parts = stripped.split()
                        if idx + 1 < len(parts):
                            result["environments"].append(parts[idx + 1])
            if "--service" in stripped:
                for part in stripped.split():
                    if part.startswith("--service="):
                        result["services"].append(part.split("=", 1)[1])
                    elif part == "--service":
                        idx = stripped.split().index("--service")
                        parts = stripped.split()
                        if idx + 1 < len(parts):
                            result["services"].append(parts[idx + 1])

        all_envs = sorted(set(e.strip('"').strip("'") for e in result["environments"]))
        result["environments"] = [e for e in all_envs if not e.startswith("$")]
        result["runtime_environments"] = [e for e in all_envs if e.startswith("$")]
        result["services"] = sorted(set(result["services"]))
        break

    return result


def _detect_service_name(ws: Path, wf: dict) -> str | None:
    """Try to detect the Railway service name for this workspace."""
    # 1. From workflow --service flag
    if wf["services"]:
        name = wf["services"][0].strip('"').strip("'")
        if not name.startswith("$"):
            return name

    # 2. From .env.local RAILWAY_SERVICE
    env_local = ws / ".env.local"
    if env_local.is_file():
        for line in env_local.read_text().splitlines():
            if line.startswith("RAILWAY_SERVICE="):
                return line.split("=", 1)[1].strip()

    # 3. From directory name as fallback
    return ws.name


async def _fetch_project_data(token: str, workspace: str) -> dict:
    """Fetch project metadata from Railway API. Shared by service and project doctors."""
    project = await _resolve_project(token)
    if "error" in project:
        return {"error": "Could not resolve project from token"}

    project_id = project.get("projectId")
    token_env_id = project.get("environmentId")

    query = """
    query project($id: String!) {
      project(id: $id) {
        name
        environments { edges { node { id name } } }
        services {
          edges {
            node {
              id name
              serviceInstances {
                edges {
                  node {
                    latestDeployment { id status createdAt }
                    domains {
                      serviceDomains { domain targetPort }
                      customDomains { domain targetPort }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
    """
    result = await _gql(token, query, {"id": project_id})
    if "error" in result:
        return {"error": "Could not query project"}

    proj = result.get("project", {})
    railway_envs = {
        e["node"]["id"]: e["node"]["name"]
        for e in proj.get("environments", {}).get("edges", [])
    }

    services = {}
    for edge in proj.get("services", {}).get("edges", []):
        svc = edge["node"]
        svc_name = svc.get("name", "unknown")
        svc_id = svc.get("id")
        instances = svc.get("serviceInstances", {}).get("edges", [])

        domains = []
        latest_deploy = None
        for inst in instances:
            node = inst.get("node", {})
            dep = node.get("latestDeployment")
            if dep:
                latest_deploy = dep
            dom_data = node.get("domains", {})
            for d in dom_data.get("serviceDomains", []):
                domains.append(d.get("domain"))
            for d in dom_data.get("customDomains", []):
                domains.append(d.get("domain"))

        services[svc_name] = {
            "id": svc_id,
            "domains": [d for d in domains if d],
            "latest_deploy": latest_deploy,
        }

    return {
        "project_id": project_id,
        "project_name": proj.get("name", "unknown"),
        "token_env_id": token_env_id,
        "railway_envs": railway_envs,
        "services": services,
    }


async def _check_repo_linking(token: str, project_data: dict) -> list:
    """Check which services are linked to GitHub repos."""
    linked = []
    for svc_name, svc_data in project_data["services"].items():
        svc_id = svc_data["id"]
        svc_query = """
        query service($id: String!) {
          service(id: $id) { id name repoTriggers { repository branch } }
        }
        """
        svc_result = await _gql(token, svc_query, {"id": svc_id})
        if "error" not in svc_result:
            triggers = svc_result.get("service", {}).get("repoTriggers", [])
            if triggers:
                linked.append(
                    {
                        "service": svc_name,
                        "repo": triggers[0].get("repository", "unknown"),
                    }
                )
    return linked


# =============================================================================
# WORKSPACE-LEVEL CHECKS (no Railway API needed — just local filesystem)
# =============================================================================


def _check_workspace(ws: Path, wf: dict, has_token: bool) -> tuple[list, int, int]:
    """Run workspace-level checks. Returns (findings, score, max_score)."""
    findings = []
    score = 0
    max_score = 0

    # 1. RAILWAY_TOKEN exists
    max_score += 1
    if has_token:
        score += 1
        findings.append(
            {
                "check": "RAILWAY_TOKEN",
                "status": "pass",
                "message": "Found in .env.local or .env",
            }
        )
    else:
        findings.append(
            {
                "check": "RAILWAY_TOKEN",
                "status": "fail",
                "message": "Not found. Add RAILWAY_TOKEN=<your-project-token> to .env.local",
                "fix": "Get a project token from Railway dashboard > Project > Settings > Tokens",
            }
        )

    # 2. .env.local in .gitignore
    max_score += 1
    gitignore = ws / ".gitignore"
    env_ignored = False
    if gitignore.is_file():
        content = gitignore.read_text()
        env_ignored = any(
            line.strip() in (".env.local", ".env*", ".env.*", "*.env.local")
            for line in content.splitlines()
        )
    if env_ignored:
        score += 1
        findings.append(
            {
                "check": ".gitignore",
                "status": "pass",
                "message": ".env.local is gitignored",
            }
        )
    else:
        findings.append(
            {
                "check": ".gitignore",
                "status": "warn",
                "message": ".env.local may not be gitignored — token could leak",
                "fix": "Add .env.local to your .gitignore file",
            }
        )

    # 3. CI/CD workflow with --environment
    max_score += 1
    has_env_flag = bool(wf.get("environments") or wf.get("runtime_environments"))
    if wf["found"]:
        if not has_env_flag:
            findings.append(
                {
                    "check": "CI/CD workflow",
                    "status": "warn",
                    "message": f"Deploy workflow found ({wf['file']}) but missing --environment flag.",
                    "fix": 'Add --environment "$RAILWAY_ENVIRONMENT" to railway up command.',
                }
            )
        elif len(wf["environments"]) > 1 and len(wf["branches"]) < len(
            wf["environments"]
        ):
            findings.append(
                {
                    "check": "CI/CD workflow",
                    "status": "warn",
                    "message": (
                        f"Workflow targets {len(wf['environments'])} environment(s) "
                        f"but only {len(wf['branches'])} branch(es) trigger it"
                    ),
                    "fix": "Add all deployment branches to on.push.branches",
                }
            )
        else:
            runtime = wf.get("runtime_environments", [])
            literal = wf["environments"]
            env_desc = (
                ", ".join(literal)
                if literal
                else ", ".join(runtime) + " (runtime variable)"
            )
            score += 1
            findings.append(
                {
                    "check": "CI/CD workflow",
                    "status": "pass",
                    "message": (
                        f"Deploy workflow covers {len(wf['branches'])} branch(es) "
                        f"({', '.join(wf['branches'])}) → environment: {env_desc}"
                    ),
                }
            )
    else:
        findings.append(
            {
                "check": "CI/CD workflow",
                "status": "warn",
                "message": "No GitHub Actions deploy workflow found",
                "fix": "Add .github/workflows/deploy.yml using the project token pattern.",
            }
        )

    # 4. Token scope vs workflow environment targets
    # (workspace check — validates the workflow file, not the Railway API)
    max_score += 1
    if (
        has_token
        and wf["found"]
        and not wf["environments"]
        and wf.get("runtime_environments")
    ):
        score += 1
        findings.append(
            {
                "check": "Token environment scope",
                "status": "pass",
                "message": "Environment set via runtime variable — ensure GitHub Actions variable matches token scope",
            }
        )
    elif has_token and wf["found"] and not has_env_flag:
        findings.append(
            {
                "check": "Token environment scope",
                "status": "warn",
                "message": "Workflow missing --environment flag — cannot verify token scope",
                "fix": "Add --environment to your workflow",
            }
        )
    else:
        findings.append(
            {
                "check": "Token environment scope",
                "status": "skip",
                "message": "Cannot verify — need both token and workflow with --environment flags",
            }
        )

    # 5. Dockerfile exists
    max_score += 1
    dockerfile = ws / "Dockerfile"
    if dockerfile.is_file():
        score += 1
        findings.append(
            {"check": "Dockerfile", "status": "pass", "message": "Dockerfile found"}
        )
    else:
        has_alt = (ws / "nixpacks.toml").is_file() or (ws / "railway.toml").is_file()
        if has_alt:
            score += 1
            findings.append(
                {
                    "check": "Dockerfile",
                    "status": "pass",
                    "message": "No Dockerfile but nixpacks/railway config found",
                }
            )
        else:
            findings.append(
                {
                    "check": "Dockerfile",
                    "status": "warn",
                    "message": "No Dockerfile — Railway will use Nixpacks auto-detection",
                    "fix": "Consider adding a Dockerfile for reproducible builds",
                }
            )

    # 6. .dockerignore
    max_score += 1
    dockerignore = ws / ".dockerignore"
    if dockerignore.is_file():
        content = dockerignore.read_text()
        has_git = ".git" in content
        has_env = ".env" in content
        issues = []
        if not has_git:
            issues.append(".git not excluded")
        if not has_env:
            issues.append(".env* not excluded")
        if issues:
            findings.append(
                {
                    "check": ".dockerignore",
                    "status": "warn",
                    "message": f".dockerignore exists but: {'; '.join(issues)}",
                    "fix": "Add .git, .env*, node_modules to .dockerignore",
                }
            )
        else:
            score += 1
            findings.append(
                {
                    "check": ".dockerignore",
                    "status": "pass",
                    "message": ".dockerignore present with .git and .env* excluded",
                }
            )
    else:
        findings.append(
            {
                "check": ".dockerignore",
                "status": "warn",
                "message": "No .dockerignore — entire directory sent as build context",
                "fix": "Create .dockerignore excluding .git, .env*, node_modules, docs",
            }
        )

    # 7. Git repository with remote
    max_score += 1
    git_dir = ws / ".git"
    has_git = git_dir.is_dir()
    has_remote = False
    if has_git:
        git_config = git_dir / "config"
        if git_config.is_file():
            has_remote = '[remote "origin"]' in git_config.read_text()
    if not has_git:
        findings.append(
            {
                "check": "Git repository",
                "status": "fail",
                "message": "Not a git repository",
                "fix": "Run: git init && git remote add origin <repo-url>",
            }
        )
    elif not has_remote:
        findings.append(
            {
                "check": "Git repository",
                "status": "fail",
                "message": "No git remote configured",
                "fix": "git remote add origin <repo-url>",
            }
        )
    else:
        score += 1
        findings.append(
            {
                "check": "Git repository",
                "status": "pass",
                "message": "Git remote configured",
            }
        )

    # 8. Uncommitted changes
    max_score += 1
    if has_git:
        import subprocess

        try:
            result_git = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                timeout=10,
            )
            dirty_files = [
                ln for ln in result_git.stdout.strip().splitlines() if ln.strip()
            ]
            if dirty_files:
                findings.append(
                    {
                        "check": "Uncommitted changes",
                        "status": "warn",
                        "message": f"{len(dirty_files)} uncommitted file(s)",
                        "fix": "Commit and push before deploying",
                    }
                )
            else:
                score += 1
                findings.append(
                    {
                        "check": "Uncommitted changes",
                        "status": "pass",
                        "message": "Working tree is clean",
                    }
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            findings.append(
                {
                    "check": "Uncommitted changes",
                    "status": "skip",
                    "message": "Could not run git status",
                }
            )
    else:
        findings.append(
            {
                "check": "Uncommitted changes",
                "status": "skip",
                "message": "Not a git repository",
            }
        )

    # 9. Package manifest + lockfile
    max_score += 1
    manifest_names = ("package.json", "pyproject.toml", "requirements.txt")
    lockfile_names = (
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lockb",
        "poetry.lock",
        "uv.lock",
    )
    search_dirs = [ws] + [
        d for d in ws.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    has_manifest = any((d / m).is_file() for d in search_dirs for m in manifest_names)
    has_lockfile = any((d / lf).is_file() for d in search_dirs for lf in lockfile_names)
    if has_manifest:
        if has_lockfile:
            score += 1
            findings.append(
                {
                    "check": "Local setup",
                    "status": "pass",
                    "message": "Package manifest and lockfile present",
                }
            )
        else:
            findings.append(
                {
                    "check": "Local setup",
                    "status": "warn",
                    "message": "Package manifest found but no lockfile — builds may be non-deterministic",
                    "fix": "Run your package manager's install command to generate a lockfile",
                }
            )
    else:
        findings.append(
            {
                "check": "Local setup",
                "status": "warn",
                "message": "No package manifest found",
                "fix": "Add package.json, pyproject.toml, or requirements.txt",
            }
        )

    # 10. CI/CD health (latest GitHub Actions run)
    max_score += 1
    has_git_remote = has_git and has_remote
    if has_git_remote:
        import subprocess

        try:
            remote_result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                timeout=10,
            )
            remote_url = remote_result.stdout.strip()
            repo_slug = None
            if "github.com" in remote_url:
                if remote_url.startswith("git@"):
                    repo_slug = remote_url.split(":")[-1].removesuffix(".git")
                elif "github.com/" in remote_url:
                    repo_slug = remote_url.split("github.com/")[-1].removesuffix(".git")

            if repo_slug:
                import json as _json

                gh_result = subprocess.run(
                    [
                        "gh",
                        "run",
                        "list",
                        "--repo",
                        repo_slug,
                        "--limit",
                        "1",
                        "--json",
                        "status,conclusion,name,headBranch",
                    ],
                    cwd=str(ws),
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if gh_result.returncode == 0 and gh_result.stdout.strip():
                    runs = _json.loads(gh_result.stdout)
                    if runs:
                        run = runs[0]
                        conclusion = (run.get("conclusion") or "").lower()
                        status_str = (run.get("status") or "").lower()
                        name = run.get("name", "unknown")
                        branch = run.get("headBranch", "unknown")
                        if conclusion == "success":
                            score += 1
                            findings.append(
                                {
                                    "check": "CI/CD health",
                                    "status": "pass",
                                    "message": f"Latest run '{name}' on {branch}: success",
                                }
                            )
                        elif status_str in ("in_progress", "queued", "waiting"):
                            findings.append(
                                {
                                    "check": "CI/CD health",
                                    "status": "warn",
                                    "message": f"Run '{name}' on {branch}: {status_str}",
                                    "fix": "Wait for CI/CD run to complete",
                                }
                            )
                        else:
                            findings.append(
                                {
                                    "check": "CI/CD health",
                                    "status": "fail",
                                    "message": f"Latest run '{name}' on {branch}: {conclusion or status_str}",
                                    "fix": "Check: gh run view --log",
                                }
                            )
                    else:
                        findings.append(
                            {
                                "check": "CI/CD health",
                                "status": "warn",
                                "message": "No GitHub Actions runs found",
                                "fix": "Push a commit to trigger the deploy workflow",
                            }
                        )
                else:
                    findings.append(
                        {
                            "check": "CI/CD health",
                            "status": "skip",
                            "message": "Could not query GitHub Actions",
                        }
                    )
            else:
                findings.append(
                    {
                        "check": "CI/CD health",
                        "status": "skip",
                        "message": "Remote is not GitHub",
                    }
                )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            findings.append(
                {
                    "check": "CI/CD health",
                    "status": "skip",
                    "message": "Could not run gh CLI",
                }
            )
    else:
        findings.append(
            {"check": "CI/CD health", "status": "skip", "message": "No git remote"}
        )

    return findings, score, max_score


# =============================================================================
# SERVICE-LEVEL CHECKS (this service only — needs Railway API)
# =============================================================================


async def doctor_service_level(workspace: str, service: str | None = None) -> dict:
    """Check a single service's Railway deployment health.

    Checks:
      1. This service's latest deployment status
      2. This service's domain configuration
      3. Deploy drift (local code vs this service's deploy time)
      4. Token scope vs workflow environment targets (API-validated)
      5. Workflow environment names match Railway environments

    Args:
        workspace: Absolute path to project directory.
        service: Service name to check. Auto-detected from workspace if omitted.
    """
    ws = Path(workspace).expanduser().resolve()
    findings = []
    score = 0
    max_score = 0

    # Load token and project data
    try:
        token = _load_token(workspace)
    except ValueError:
        return {
            "score": "0/0",
            "findings": [
                {
                    "check": "Token",
                    "status": "fail",
                    "message": "No RAILWAY_TOKEN — cannot check service",
                }
            ],
            "healthy": False,
        }

    project_data = await _fetch_project_data(token, workspace)
    if "error" in project_data:
        return {
            "score": "0/0",
            "findings": [
                {
                    "check": "Railway API",
                    "status": "fail",
                    "message": project_data["error"],
                }
            ],
            "healthy": False,
        }

    # Detect service name
    wf = _parse_workflow_details(ws / ".github" / "workflows")
    svc_name = service or _detect_service_name(ws, wf)
    svc_data = project_data["services"].get(svc_name)

    if not svc_data:
        return {
            "score": "0/0",
            "findings": [
                {
                    "check": "Service",
                    "status": "fail",
                    "message": f"Service '{svc_name}' not found in Railway project '{project_data['project_name']}'",
                    "fix": f"Available services: {', '.join(project_data['services'].keys())}",
                }
            ],
            "healthy": False,
            "service": svc_name,
        }

    # 1. This service's deployment health
    max_score += 1
    dep = svc_data.get("latest_deploy")
    if dep:
        status = (dep.get("status") or "").upper()
        healthy_statuses = {"SUCCESS", "SLEEPING"}
        in_progress = {"BUILDING", "DEPLOYING", "INITIALIZING", "WAITING"}
        if status in healthy_statuses:
            score += 1
            findings.append(
                {
                    "check": "Deployment health",
                    "status": "pass",
                    "message": f"{svc_name}: latest deployment {status}",
                }
            )
        elif status in in_progress:
            findings.append(
                {
                    "check": "Deployment health",
                    "status": "warn",
                    "message": f"{svc_name}: deployment {status} — not done yet",
                    "fix": "Wait for deploy to complete, then re-run",
                }
            )
        else:
            findings.append(
                {
                    "check": "Deployment health",
                    "status": "fail",
                    "message": f"{svc_name}: latest deployment {status}",
                    "fix": "Check railguey_deployment_logs for error details",
                }
            )
    else:
        findings.append(
            {
                "check": "Deployment health",
                "status": "warn",
                "message": f"{svc_name}: no deployments found",
                "fix": "Deploy with railguey_deploy or push to trigger CI/CD",
            }
        )

    # 2. This service's domain configuration
    max_score += 1
    if svc_data["domains"]:
        score += 1
        findings.append(
            {
                "check": "Domain",
                "status": "pass",
                "message": f"{svc_name}: {', '.join(svc_data['domains'])}",
            }
        )
    else:
        findings.append(
            {
                "check": "Domain",
                "status": "warn",
                "message": f"{svc_name}: no public domain configured",
                "fix": "Use railguey_domain to generate one (or skip if this is a background worker)",
            }
        )

    # 3. Deploy drift (local code vs this service's deploy)
    max_score += 1
    git_dir = ws / ".git"
    if git_dir.is_dir() and dep and dep.get("createdAt"):
        import subprocess
        from datetime import datetime, timezone

        try:
            head_result = subprocess.run(
                ["git", "log", "-1", "--format=%cI"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                timeout=10,
            )
            local_commit_str = head_result.stdout.strip()
            if local_commit_str:
                local_time = datetime.fromisoformat(local_commit_str)
                if local_time.tzinfo is None:
                    local_time = local_time.replace(tzinfo=timezone.utc)

                deploy_str = dep["createdAt"]
                deploy_time = datetime.fromisoformat(deploy_str.replace("Z", "+00:00"))

                if local_time > deploy_time:
                    delta = local_time - deploy_time
                    mins = int(delta.total_seconds() // 60)
                    findings.append(
                        {
                            "check": "Deploy drift",
                            "status": "warn",
                            "message": f"{svc_name}: local code is {mins}m ahead of deployed code",
                            "fix": "Push to trigger CI/CD or run railguey_deploy",
                        }
                    )
                else:
                    score += 1
                    findings.append(
                        {
                            "check": "Deploy drift",
                            "status": "pass",
                            "message": f"{svc_name}: deployed code is up to date",
                        }
                    )
            else:
                findings.append(
                    {
                        "check": "Deploy drift",
                        "status": "skip",
                        "message": "Could not get local commit time",
                    }
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            findings.append(
                {
                    "check": "Deploy drift",
                    "status": "skip",
                    "message": "Could not determine deploy drift",
                }
            )
    else:
        findings.append(
            {
                "check": "Deploy drift",
                "status": "skip",
                "message": "Need git repo and deployment to check drift",
            }
        )

    # 4. Token scope vs workflow environments (API-validated)
    max_score += 1
    token_env_id = project_data.get("token_env_id")
    railway_envs = project_data.get("railway_envs", {})
    if token_env_id and wf["found"] and wf["environments"]:
        token_env_name = railway_envs.get(token_env_id, "unknown")
        workflow_envs = set(wf["environments"])
        uncovered = workflow_envs - {token_env_name}
        if uncovered:
            # Check if the account system covers the gap
            try:
                from railguey.lib.accounts import list_accounts

                accts = list_accounts()
                acct_names = set(accts.get("accounts", {}).keys())
                has_accounts = len(acct_names) >= 2
            except Exception:
                has_accounts = False

            if has_accounts:
                score += 1
                findings.append(
                    {
                        "check": "Token environment scope",
                        "status": "pass",
                        "message": (
                            f"Token scoped to '{token_env_name}' but "
                            f"account system covers {', '.join(sorted(uncovered))} — "
                            f"use railguey_account_default to switch"
                        ),
                    }
                )
            else:
                findings.append(
                    {
                        "check": "Token environment scope",
                        "status": "fail",
                        "message": (
                            f"Token scoped to '{token_env_name}' but workflow targets: "
                            f"{', '.join(sorted(uncovered))}"
                        ),
                        "fix": (
                            "Register tokens for each environment with railguey_account_add, "
                            "then switch with railguey_account_default"
                        ),
                    }
                )
        else:
            score += 1
            findings.append(
                {
                    "check": "Token environment scope",
                    "status": "pass",
                    "message": f"Token scoped to '{token_env_name}' — matches workflow",
                }
            )
    elif wf["found"] and wf.get("runtime_environments"):
        score += 1
        findings.append(
            {
                "check": "Token environment scope",
                "status": "pass",
                "message": "Environment set via runtime variable",
            }
        )
    else:
        findings.append(
            {
                "check": "Token environment scope",
                "status": "skip",
                "message": "Cannot verify — need workflow with --environment flags",
            }
        )

    # 5. Workflow environment names match Railway
    max_score += 1
    if wf["found"] and wf["environments"] and railway_envs:
        railway_env_names = set(railway_envs.values())
        workflow_envs = set(wf["environments"])
        invalid = workflow_envs - railway_env_names
        if invalid:
            findings.append(
                {
                    "check": "Environment names",
                    "status": "fail",
                    "message": (
                        f"Workflow references unknown environment(s): {', '.join(sorted(invalid))}. "
                        f"Railway has: {', '.join(sorted(railway_env_names))}"
                    ),
                    "fix": "Fix --environment values to match Railway environment names",
                }
            )
        else:
            score += 1
            findings.append(
                {
                    "check": "Environment names",
                    "status": "pass",
                    "message": f"Workflow environments match Railway: {', '.join(sorted(workflow_envs))}",
                }
            )
    elif wf["found"] and wf.get("runtime_environments"):
        score += 1
        findings.append(
            {
                "check": "Environment names",
                "status": "pass",
                "message": "Environment set via runtime variable",
            }
        )
    else:
        findings.append(
            {"check": "Environment names", "status": "skip", "message": "Cannot verify"}
        )

    skipped = sum(1 for f in findings if f["status"] == "skip")
    effective_max = max_score - skipped

    return {
        "service": svc_name,
        "score": f"{score}/{effective_max}",
        "findings": findings,
        "healthy": score == effective_max,
    }


# =============================================================================
# PROJECT-LEVEL CHECKS (all services — cross-service visibility)
# =============================================================================


async def doctor_project_level(workspace: str) -> dict:
    """Check the entire Railway project's health.

    Checks:
      1. Repo linking across all services
      2. Failed deployments across all services
      3. Domain coverage across all services
      4. Deploy drift across all services

    Args:
        workspace: Absolute path to project directory (for token).
    """
    findings = []
    score = 0
    max_score = 0

    try:
        token = _load_token(workspace)
    except ValueError:
        return {
            "score": "0/0",
            "findings": [
                {
                    "check": "Token",
                    "status": "fail",
                    "message": "No RAILWAY_TOKEN — cannot check project",
                }
            ],
            "healthy": False,
        }

    project_data = await _fetch_project_data(token, workspace)
    if "error" in project_data:
        return {
            "score": "0/0",
            "findings": [
                {
                    "check": "Railway API",
                    "status": "fail",
                    "message": project_data["error"],
                }
            ],
            "healthy": False,
        }

    services = project_data["services"]
    project_name = project_data["project_name"]

    # 1. Repo linking audit
    max_score += 1
    linked = await _check_repo_linking(token, project_data)
    if linked:
        findings.append(
            {
                "check": "GitHub repo linking",
                "status": "warn",
                "message": f"{len(linked)} service(s) linked to GitHub repos (brittle auto-deploy)",
                "linked": linked,
                "fix": "Use railguey_unlink_repo, then set up GitHub Actions CI/CD",
            }
        )
    else:
        score += 1
        findings.append(
            {
                "check": "GitHub repo linking",
                "status": "pass",
                "message": "No services linked to GitHub repos (good — using token-based deploys)",
            }
        )

    # 2. Deployment health across all services
    max_score += 1
    healthy_statuses = {"SUCCESS", "SLEEPING"}
    failed = []
    in_progress = []
    for svc_name, svc_data in services.items():
        dep = svc_data.get("latest_deploy")
        if dep:
            status = (dep.get("status") or "").upper()
            if status in {"BUILDING", "DEPLOYING", "INITIALIZING", "WAITING"}:
                in_progress.append(f"{svc_name} ({status})")
            elif status not in healthy_statuses:
                failed.append(f"{svc_name} ({status})")
    if failed:
        findings.append(
            {
                "check": "Deployment health",
                "status": "fail",
                "message": f"Failed: {', '.join(failed)}",
                "fix": "Check railguey_deployment_logs for each failed service",
            }
        )
    elif in_progress:
        findings.append(
            {
                "check": "Deployment health",
                "status": "warn",
                "message": f"In progress: {', '.join(in_progress)}",
                "fix": "Wait for deploys to complete",
            }
        )
    else:
        score += 1
        findings.append(
            {
                "check": "Deployment health",
                "status": "pass",
                "message": "All services healthy",
            }
        )

    # 3. Domain coverage
    max_score += 1
    no_domain = [name for name, data in services.items() if not data["domains"]]
    if no_domain:
        findings.append(
            {
                "check": "Domain coverage",
                "status": "warn",
                "message": f"No domain: {', '.join(no_domain)}",
                "fix": "Use railguey_domain (or skip for background workers)",
            }
        )
    else:
        score += 1
        findings.append(
            {
                "check": "Domain coverage",
                "status": "pass",
                "message": "All services have at least one domain",
            }
        )

    # 4. Deploy drift across all services
    max_score += 1
    ws = Path(workspace).expanduser().resolve()
    git_dir = ws / ".git"
    if git_dir.is_dir():
        import subprocess
        from datetime import datetime, timezone

        try:
            head_result = subprocess.run(
                ["git", "log", "-1", "--format=%cI"],
                cwd=str(ws),
                capture_output=True,
                text=True,
                timeout=10,
            )
            local_commit_str = head_result.stdout.strip()
            if local_commit_str:
                local_time = datetime.fromisoformat(local_commit_str)
                if local_time.tzinfo is None:
                    local_time = local_time.replace(tzinfo=timezone.utc)

                stale = []
                for svc_name, svc_data in services.items():
                    dep = svc_data.get("latest_deploy")
                    if dep and dep.get("createdAt"):
                        status = (dep.get("status") or "").upper()
                        if status != "SUCCESS":
                            stale.append(f"{svc_name} ({status.lower()})")
                            continue
                        deploy_time = datetime.fromisoformat(
                            dep["createdAt"].replace("Z", "+00:00")
                        )
                        if local_time > deploy_time:
                            mins = int((local_time - deploy_time).total_seconds() // 60)
                            stale.append(f"{svc_name} ({mins}m behind)")

                if stale:
                    findings.append(
                        {
                            "check": "Deploy drift",
                            "status": "warn",
                            "message": f"Behind: {', '.join(stale)}",
                            "fix": "Deploy or push to trigger CI/CD",
                        }
                    )
                else:
                    score += 1
                    findings.append(
                        {
                            "check": "Deploy drift",
                            "status": "pass",
                            "message": "All services up to date",
                        }
                    )
            else:
                findings.append(
                    {
                        "check": "Deploy drift",
                        "status": "skip",
                        "message": "Could not get local commit time",
                    }
                )
        except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
            findings.append(
                {
                    "check": "Deploy drift",
                    "status": "skip",
                    "message": "Could not determine drift",
                }
            )
    else:
        findings.append(
            {
                "check": "Deploy drift",
                "status": "skip",
                "message": "Not a git repository",
            }
        )

    skipped = sum(1 for f in findings if f["status"] == "skip")
    effective_max = max_score - skipped

    return {
        "project": project_name,
        "score": f"{score}/{effective_max}",
        "findings": findings,
        "healthy": score == effective_max,
    }


# =============================================================================
# COMBINED DOCTOR (entry point — workspace checks + both sub-doctors)
# =============================================================================


def _build_remediation(findings: list, wf: dict) -> tuple[list, list]:
    """Build remediation plan + verify_after from findings."""
    remediation = []
    default_branch = wf["branches"][0] if wf["branches"] else "main"
    service_names = wf["services"] if wf["services"] else []

    for f in findings:
        if f["status"] in ("pass", "skip"):
            continue

        check = f["check"]
        if check == "RAILWAY_TOKEN":
            remediation.append(
                {
                    "intent": "Add Railway project token",
                    "detail": "Get from Railway dashboard > Project > Settings > Tokens",
                    "file": ".env.local",
                    "format": "RAILWAY_TOKEN=<token>",
                    "suggested_tool": "railguey_variable_set or manual edit",
                }
            )
        elif check == ".gitignore":
            remediation.append(
                {
                    "intent": "Protect .env.local from git",
                    "file": ".gitignore",
                    "append_line": ".env.local",
                    "suggested_tool": "Edit .gitignore",
                }
            )
        elif check == "CI/CD workflow":
            remediation.append(
                {
                    "intent": "Create deploy workflow",
                    "detail": f"Deploy to Railway on push to {default_branch}",
                    "file": ".github/workflows/deploy.yml",
                    "content": _WORKFLOW_TEMPLATE.format(branch=default_branch),
                    "github_secret": {"name": "RAILWAY_TOKEN", "source": ".env.local"},
                    "github_variable": {
                        "name": "RAILWAY_SERVICE",
                        "value": service_names[0]
                        if service_names
                        else "<your-service-name>",
                    },
                    "suggested_tool": "Write workflow, then gh secret set + gh variable set",
                }
            )
        elif check == "GitHub repo linking":
            for svc in f.get("linked", []):
                remediation.append(
                    {
                        "intent": f"Unlink {svc['service']} from {svc['repo']}",
                        "suggested_tool": "railguey_unlink_repo",
                    }
                )
        elif check == "Token environment scope":
            remediation.append(
                {
                    "intent": "Fix token environment coverage",
                    "detail": f["message"],
                    "suggested_tool": "railguey_account_add + railguey_account_default",
                }
            )
        elif check == "Environment names":
            remediation.append(
                {
                    "intent": "Fix workflow environment names",
                    "detail": f["message"],
                    "suggested_tool": "Edit --environment flags in workflow",
                }
            )
        elif check == ".dockerignore":
            remediation.append(
                {
                    "intent": "Create or fix .dockerignore",
                    "file": ".dockerignore",
                    "suggested_tool": "Write .dockerignore file",
                }
            )
        elif check == "Domain" or check == "Domain coverage":
            remediation.append(
                {
                    "intent": "Configure domain",
                    "detail": f["message"],
                    "suggested_tool": "railguey_domain",
                }
            )
        elif check == "Deploy drift":
            remediation.append(
                {
                    "intent": "Deploy latest code",
                    "detail": f["message"],
                    "suggested_tool": "railguey_deploy or git push",
                }
            )
        elif check == "Deployment health":
            remediation.append(
                {
                    "intent": "Fix failed deployments",
                    "detail": f["message"],
                    "suggested_tool": "railguey_deployment_logs then railguey_redeploy",
                }
            )
        elif check == "CI/CD health":
            remediation.append(
                {
                    "intent": "Fix CI/CD pipeline",
                    "detail": f["message"],
                    "suggested_tool": "gh run view --log",
                }
            )
        elif check == "Git repository":
            remediation.append(
                {"intent": "Set up git remote", "suggested_tool": "gh repo create"}
            )
        elif check == "Local setup":
            remediation.append(
                {
                    "intent": "Add lockfile",
                    "detail": f["message"],
                    "suggested_tool": "Run package manager install to generate lockfile",
                }
            )

    verify_after = []
    if remediation:
        verify_after = [
            {
                "intent": "Confirm GitHub Actions deploy succeeded",
                "suggested_tool": "gh run list --limit 1",
            },
            {
                "intent": "Confirm Railway deployment landed",
                "suggested_tool": "railguey_deployments",
            },
            {
                "intent": "Re-run doctor to confirm all checks pass",
                "suggested_tool": "railguey_doctor",
            },
        ]

    return remediation, verify_after


async def doctor(workspace: str) -> dict:
    """Full workspace audit — workspace checks + service-level + project-level.

    Three layers:
      - Workspace: local filesystem checks (token, .gitignore, Dockerfile, etc.)
      - Service: this service's Railway health (deployment, domain, drift)
      - Project: whole Railway project (cross-service issues, informational)

    Returns structured report with separate scores per layer.
    """
    ws = Path(workspace).expanduser().resolve()

    # Load token early — needed to decide what we can check
    has_token = False
    try:
        _load_token(workspace)
        has_token = True
    except ValueError:
        pass

    wf = _parse_workflow_details(ws / ".github" / "workflows")

    # Layer 1: Workspace checks
    ws_findings, ws_score, ws_max = _check_workspace(ws, wf, has_token)

    # Layer 2: Service-level checks
    svc_result = None
    if has_token:
        svc_result = await doctor_service_level(workspace)

    # Layer 3: Project-level checks
    proj_result = None
    if has_token:
        proj_result = await doctor_project_level(workspace)

    # Layer 4: PyPI drift check (if this workspace is a pypi_package)
    pypi_result = None
    try:
        from railguey.lib.orchestrate import _load_all_registries, _expand_home

        for reg in _load_all_registries():
            for svc in reg.get("services", []):
                if svc.get("type") != "pypi_package":
                    continue
                svc_ws = _expand_home(svc.get("workspace"))
                if svc_ws and Path(svc_ws).resolve() == ws:
                    from railguey.lib.tools import pypi_status

                    pypi_result = await pypi_status([svc["name"]])
                    break
            if pypi_result:
                break
    except Exception:
        pass

    # Combine all findings for remediation
    all_findings = list(ws_findings)
    if svc_result:
        all_findings.extend(svc_result.get("findings", []))
    if proj_result:
        all_findings.extend(proj_result.get("findings", []))
    if pypi_result and "packages" in pypi_result:
        for pkg in pypi_result["packages"]:
            status = pkg.get("status", "UNKNOWN")
            if status == "IN_SYNC":
                all_findings.append(
                    {
                        "check": "pypi_sync",
                        "status": "pass",
                        "detail": f"PyPI {pkg.get('pypi_version')} == local {pkg.get('local_version')}",
                    }
                )
            elif status == "GIT_AHEAD":
                all_findings.append(
                    {
                        "check": "pypi_sync",
                        "status": "warn",
                        "detail": f"Local {pkg.get('local_version')} ahead of PyPI {pkg.get('pypi_version')} — publish pending?",
                    }
                )
            elif status == "PUBLISH_FAILED":
                all_findings.append(
                    {
                        "check": "pypi_sync",
                        "status": "fail",
                        "detail": f"Tag pushed but PyPI has {pkg.get('pypi_version')} — publish may have failed",
                    }
                )
            else:
                all_findings.append(
                    {
                        "check": "pypi_sync",
                        "status": "warn",
                        "detail": f"PyPI status: {status}",
                    }
                )

    remediation, verify_after = _build_remediation(all_findings, wf)

    # Workspace score (skipped don't count)
    ws_skipped = sum(1 for f in ws_findings if f["status"] == "skip")
    ws_effective = ws_max - ws_skipped

    # Overall health
    all_healthy = ws_score == ws_effective
    if svc_result:
        all_healthy = all_healthy and svc_result.get("healthy", False)
    if proj_result:
        all_healthy = all_healthy and proj_result.get("healthy", False)

    result: dict = {
        "workspace": {
            "score": f"{ws_score}/{ws_effective}",
            "findings": ws_findings,
            "healthy": ws_score == ws_effective,
        },
        "healthy": all_healthy,
    }

    if svc_result:
        result["service"] = svc_result
    if proj_result:
        result["project"] = proj_result
    if pypi_result and "packages" in pypi_result:
        result["pypi"] = pypi_result
    if remediation:
        result["remediation"] = remediation
    if verify_after:
        result["verify_after"] = verify_after

    return result
