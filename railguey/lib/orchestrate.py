"""Deploy orchestration — registry, preflight, verify, deploy_plan.

Reads service-registry.yaml and provides four high-level tools that
turn railguey from a Railway API wrapper into a deploy orchestrator.
"""

import asyncio
import time
from pathlib import Path

import httpx
import yaml

from railguey.lib.token import _load_token
from railguey.lib.graphql import _gql, _resolve_project, _resolve_service_id


# ── Registry loading ────────────────────────────────────────────────

_REGISTRY_PATHS = [
    Path(__file__).parent.parent.parent / "registry" / "service-registry.yaml",
    Path.home() / ".railguey" / "service-registry.yaml",
]


def _load_registry() -> dict:
    """Load and parse the service registry YAML."""
    for path in _REGISTRY_PATHS:
        if path.exists():
            with open(path) as f:
                return yaml.safe_load(f)
    return {"error": f"Registry not found. Searched: {[str(p) for p in _REGISTRY_PATHS]}"}


def _find_service(registry: dict, name: str) -> dict | None:
    """Find a service entry by name."""
    for svc in registry.get("services", []):
        if svc.get("name") == name:
            return svc
    return None


def _expand_home(path: str | None) -> str | None:
    """Expand ~ in workspace paths."""
    if path and path.startswith("~"):
        return str(Path(path).expanduser())
    return path


# ── Tool 1: registry ───────────────────────────────────────────────

async def registry(service: str | None = None) -> dict:
    """Read the service registry. Returns metadata for one or all services.

    Args:
        service: Optional service name. If omitted, returns all services.
    """
    reg = _load_registry()
    if "error" in reg:
        return reg

    if service:
        svc = _find_service(reg, service)
        if not svc:
            names = [s["name"] for s in reg.get("services", [])]
            return {"error": f"Service '{service}' not in registry. Known: {names}"}
        return {"service": svc, "org": reg.get("org"), "defaults": reg.get("defaults")}

    return {
        "org": reg.get("org"),
        "defaults": reg.get("defaults"),
        "resources": reg.get("resources"),
        "services": reg.get("services", []),
        "count": len(reg.get("services", [])),
    }


# ── Tool 2: preflight ──────────────────────────────────────────────

async def preflight(service: str, workspace: str | None = None) -> dict:
    """Pre-push checks for a service. Returns go/no-go with reasons.

    Checks:
    1. Registry entry exists
    2. Git branch matches registry deploy.branch
    3. Working tree is clean (no uncommitted changes)
    4. No in-progress Railway deployments (concurrency lock)
    5. Dependencies with required_before_deploy gate are deployed
    """
    reg = _load_registry()
    if "error" in reg:
        return reg

    svc = _find_service(reg, service)
    if not svc:
        names = [s["name"] for s in reg.get("services", [])]
        return {"go": False, "reasons": [f"Service '{service}' not in registry. Known: {names}"]}

    ws = workspace or _expand_home(svc.get("workspace"))
    checks = []
    blocking = []

    # Check 1: branch
    deploy_branch = svc.get("deploy", {}).get("branch")
    if deploy_branch and ws:
        import subprocess
        try:
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                cwd=ws, capture_output=True, text=True, timeout=5,
            )
            current_branch = result.stdout.strip()
            if current_branch == deploy_branch:
                checks.append({"check": "branch", "status": "pass",
                               "detail": f"On {current_branch}"})
            else:
                blocking.append({"check": "branch", "status": "fail",
                                 "detail": f"On '{current_branch}', registry expects '{deploy_branch}'"})
        except Exception as e:
            checks.append({"check": "branch", "status": "skip", "detail": str(e)})

    # Check 2: clean worktree
    defaults = reg.get("defaults", {}).get("preflight", {})
    if defaults.get("require_clean_worktree", True) and ws:
        import subprocess
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=ws, capture_output=True, text=True, timeout=5,
            )
            dirty_files = [l for l in result.stdout.strip().split("\n") if l.strip()]
            if not dirty_files:
                checks.append({"check": "worktree", "status": "pass", "detail": "Clean"})
            else:
                blocking.append({"check": "worktree", "status": "fail",
                                 "detail": f"{len(dirty_files)} uncommitted files"})
        except Exception as e:
            checks.append({"check": "worktree", "status": "skip", "detail": str(e)})

    # Check 3: no in-progress deploys (Railway services only)
    if svc.get("type") == "railway_service" and ws:
        try:
            token = _load_token(ws)
            project = await _resolve_project(token)
            if "error" not in project:
                project_id = project.get("projectId", "")
                service_id = await _resolve_service_id(token, project_id, service)
                if service_id:
                    dep_query = """
                    query deployments($input: DeploymentListInput!) {
                      deployments(input: $input, first: 1) {
                        edges { node { id status } }
                      }
                    }
                    """
                    dep_result = await _gql(token, dep_query, {
                        "input": {"projectId": project_id, "serviceId": service_id}
                    })
                    edges = dep_result.get("deployments", {}).get("edges", [])
                    if edges:
                        latest_status = edges[0]["node"].get("status", "")
                        if latest_status in ("BUILDING", "DEPLOYING", "INITIALIZING"):
                            blocking.append({
                                "check": "concurrency", "status": "fail",
                                "detail": f"Deploy already in progress (status: {latest_status})"
                            })
                        else:
                            checks.append({"check": "concurrency", "status": "pass",
                                           "detail": f"No active deploy (last: {latest_status})"})
                else:
                    checks.append({"check": "concurrency", "status": "skip",
                                   "detail": f"Service '{service}' not found in Railway project"})
        except Exception as e:
            checks.append({"check": "concurrency", "status": "skip", "detail": str(e)})

    # Check 4: dependencies with required_before_deploy
    for dep in svc.get("depends_on", []):
        if dep.get("gate") != "required_before_deploy":
            continue
        target_name = dep.get("target")
        target_svc = _find_service(reg, target_name)
        if not target_svc:
            blocking.append({"check": f"dependency:{target_name}", "status": "fail",
                             "detail": f"Dependency '{target_name}' not in registry"})
            continue

        # For migrations: check that all are synced
        if target_svc.get("type") == "migrations":
            target_ws = _expand_home(target_svc.get("workspace"))
            if target_ws:
                import subprocess
                try:
                    result = subprocess.run(
                        ["npx", "supabase", "migration", "list", "--linked"],
                        cwd=target_ws, capture_output=True, text=True, timeout=30,
                    )
                    # Look for lines where Local has a value but Remote is empty
                    unsynced = []
                    for line in result.stdout.split("\n"):
                        # Table format: local | remote | time
                        parts = [p.strip() for p in line.split("|")]
                        if len(parts) >= 2 and parts[0] and not parts[1]:
                            unsynced.append(parts[0])
                    if unsynced:
                        blocking.append({
                            "check": f"dependency:{target_name}", "status": "fail",
                            "detail": f"Undeployed migrations: {unsynced}"
                        })
                    else:
                        checks.append({"check": f"dependency:{target_name}", "status": "pass",
                                       "detail": "All migrations synced"})
                except Exception as e:
                    checks.append({"check": f"dependency:{target_name}", "status": "skip",
                                   "detail": str(e)})

        # For Railway services: check latest deploy is SUCCESS
        elif target_svc.get("type") == "railway_service":
            target_ws = _expand_home(target_svc.get("workspace"))
            if not target_ws:
                blocking.append({"check": f"dependency:{target_name}", "status": "fail",
                                 "detail": f"Required dependency '{target_name}' has no workspace configured"})
            else:
                try:
                    token = _load_token(target_ws)
                    project = await _resolve_project(token)
                    if "error" not in project:
                        project_id = project.get("projectId", "")
                        sid = await _resolve_service_id(token, project_id, target_name)
                        if sid:
                            dep_query = """
                            query deployments($input: DeploymentListInput!) {
                              deployments(input: $input, first: 1) {
                                edges { node { status } }
                              }
                            }
                            """
                            dep_result = await _gql(token, dep_query, {
                                "input": {"projectId": project_id, "serviceId": sid}
                            })
                            edges = dep_result.get("deployments", {}).get("edges", [])
                            if edges and edges[0]["node"].get("status") == "SUCCESS":
                                checks.append({"check": f"dependency:{target_name}", "status": "pass",
                                               "detail": "Latest deploy SUCCESS"})
                            else:
                                status = edges[0]["node"].get("status") if edges else "none"
                                blocking.append({"check": f"dependency:{target_name}", "status": "fail",
                                                 "detail": f"Latest deploy: {status}"})
                except Exception as e:
                    checks.append({"check": f"dependency:{target_name}", "status": "skip",
                                   "detail": str(e)})

    go = len(blocking) == 0
    return {
        "go": go,
        "service": service,
        "passed": checks,
        "blocking": blocking,
        "summary": "All preflight checks passed" if go else f"{len(blocking)} blocking issue(s)",
    }


# ── Tool 3: verify ─────────────────────────────────────────────────

async def verify(service: str, workspace: str | None = None, deployment_id: str | None = None) -> dict:
    """Post-push verification. Polls Railway, checks health, scans logs.

    Returns pass/fail with evidence.
    """
    reg = _load_registry()
    if "error" in reg:
        return reg

    svc = _find_service(reg, service)
    if not svc:
        return {"pass": False, "error": f"Service '{service}' not in registry"}

    ws = workspace or _expand_home(svc.get("workspace"))
    if not ws:
        return {"pass": False, "error": "No workspace path available"}

    svc_verify = svc.get("verify", {})
    defaults = reg.get("defaults", {}).get("verify", {})
    timeout = svc_verify.get("timeout_seconds", defaults.get("timeout_seconds", 900))
    poll_interval = defaults.get("poll_interval_seconds", 10)
    streak_target = svc_verify.get("success_streak", defaults.get("success_streak", 3))
    log_tail = defaults.get("log_tail_lines", 50)
    fail_patterns = (
        svc.get("health", {}).get("log_patterns", {}).get("fail_fast", [])
        + defaults.get("fail_fast_patterns", [])
    )

    results = {"service": service, "checks": []}

    # Skip Railway polling for non-Railway services
    if svc.get("type") != "railway_service":
        results["checks"].append({"check": "deploy_poll", "status": "skip",
                                   "detail": f"Not a Railway service (type: {svc.get('type')})"})
        results["pass"] = True
        return results

    # Step 1: Poll Railway deployment until terminal state
    try:
        token = _load_token(ws)
        project = await _resolve_project(token)
        if "error" in project:
            results["pass"] = False
            results["checks"].append({"check": "deploy_poll", "status": "fail", "detail": str(project)})
            return results

        project_id = project.get("projectId", "")
        service_id = await _resolve_service_id(token, project_id, service)
        if not service_id:
            results["pass"] = False
            results["checks"].append({"check": "deploy_poll", "status": "fail",
                                       "detail": f"Service '{service}' not found in Railway"})
            return results

        dep_query = """
        query deployments($input: DeploymentListInput!) {
          deployments(input: $input, first: 1) {
            edges { node { id status createdAt } }
          }
        }
        """

        start_time = time.time()
        final_status = None
        final_deployment_id = deployment_id

        while time.time() - start_time < timeout:
            dep_result = await _gql(token, dep_query, {
                "input": {"projectId": project_id, "serviceId": service_id}
            })
            edges = dep_result.get("deployments", {}).get("edges", [])
            if edges:
                node = edges[0]["node"]
                final_deployment_id = node.get("id")
                final_status = node.get("status")
                if final_status in ("SUCCESS", "FAILED", "CRASHED", "REMOVED"):
                    break
            await asyncio.sleep(poll_interval)

        if final_status == "SUCCESS":
            results["checks"].append({"check": "deploy_poll", "status": "pass",
                                       "detail": f"Deploy {final_status}",
                                       "deployment_id": final_deployment_id})
        elif final_status:
            results["checks"].append({"check": "deploy_poll", "status": "fail",
                                       "detail": f"Deploy {final_status}",
                                       "deployment_id": final_deployment_id})
            results["pass"] = False
            return results
        else:
            results["checks"].append({"check": "deploy_poll", "status": "fail",
                                       "detail": f"Timed out after {timeout}s"})
            results["pass"] = False
            return results

        # Step 2: Log tail scan for fail-fast patterns
        if final_deployment_id and fail_patterns:
            log_query = """
            query deploymentLogs($deploymentId: String!, $limit: Int) {
              deploymentLogs(deploymentId: $deploymentId, limit: $limit) {
                message timestamp severity
              }
            }
            """
            log_result = await _gql(token, log_query, {
                "deploymentId": final_deployment_id, "limit": log_tail,
            })
            log_entries = log_result.get("deploymentLogs", [])
            found_issues = []
            for entry in log_entries:
                msg = entry.get("message", "")
                for pattern in fail_patterns:
                    if pattern.lower() in msg.lower():
                        found_issues.append({"pattern": pattern, "line": msg.strip()[:200]})
                        break

            if found_issues:
                results["checks"].append({
                    "check": "log_scan", "status": "fail",
                    "detail": f"Found {len(found_issues)} fail-fast pattern(s)",
                    "matches": found_issues[:10],
                })
                results["pass"] = False
                return results
            else:
                results["checks"].append({"check": "log_scan", "status": "pass",
                                           "detail": f"No fail-fast patterns in {len(log_entries)} log lines"})

        # Step 3: HTTP health check
        health_http = svc.get("health", {}).get("http")
        if health_http:
            # Resolve the service domain from Railway
            svc_query = """
            query service($id: String!) {
              service(id: $id) {
                serviceInstances {
                  edges {
                    node {
                      domains { serviceDomains { domain } customDomains { domain } }
                    }
                  }
                }
              }
            }
            """
            svc_result = await _gql(token, svc_query, {"id": service_id})
            domains = []
            for edge in svc_result.get("service", {}).get("serviceInstances", {}).get("edges", []):
                dom_data = edge["node"].get("domains", {}) or {}
                domains.extend([d["domain"] for d in dom_data.get("customDomains", []) if d.get("domain")])
                domains.extend([d["domain"] for d in dom_data.get("serviceDomains", []) if d.get("domain")])

            if domains:
                health_path = health_http.get("path", "/health")
                expect_status = health_http.get("expect_status", 200)
                url = f"https://{domains[0]}{health_path}"

                streak = 0
                last_error = None
                for _ in range(streak_target + 2):
                    try:
                        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                            resp = await client.get(url)
                            if resp.status_code == expect_status:
                                streak += 1
                                if streak >= streak_target:
                                    break
                            else:
                                streak = 0
                                last_error = f"Got {resp.status_code}, expected {expect_status}"
                    except Exception as e:
                        streak = 0
                        last_error = str(e)
                    await asyncio.sleep(3)

                if streak >= streak_target:
                    results["checks"].append({
                        "check": "health_http", "status": "pass",
                        "detail": f"{url} returned {expect_status} x{streak}",
                    })
                else:
                    results["checks"].append({
                        "check": "health_http", "status": "fail",
                        "detail": f"Health check failed: {last_error}",
                        "url": url,
                    })
                    results["pass"] = False
                    return results
            else:
                results["checks"].append({"check": "health_http", "status": "skip",
                                           "detail": "No domain found on Railway service"})

    except Exception as e:
        results["pass"] = False
        results["checks"].append({"check": "verify", "status": "error", "detail": str(e)})
        return results

    results["pass"] = True
    return results


# ── Tool 4: deploy_plan ────────────────────────────────────────────

async def deploy_plan(repos: list[str]) -> dict:
    """Given changed repos, return an ordered deploy plan with stages and gates.

    Topologically sorts services by dependencies, groups into stages:
      Stage 1: migrations (blocking gate)
      Stage 2: APIs and config services
      Stage 3: frontends and workers

    Args:
        repos: List of repo names that have changes (e.g. ["data-daemon", "cerebro-migrations"])
    """
    reg = _load_registry()
    if "error" in reg:
        return reg

    all_services = reg.get("services", [])

    # Map repo names to affected services
    affected = []
    for svc in all_services:
        if svc.get("repo") in repos:
            affected.append(svc)

    if not affected:
        return {"error": f"No services match repos: {repos}",
                "known_repos": list({s.get("repo") for s in all_services if s.get("repo")})}

    affected_names = {s["name"] for s in affected}

    # Expand: add required_before_deploy dependencies
    expanded = set()
    to_process = list(affected_names)
    while to_process:
        name = to_process.pop()
        if name in expanded:
            continue
        expanded.add(name)
        svc = _find_service(reg, name)
        if svc:
            for dep in svc.get("depends_on", []):
                if dep.get("gate") == "required_before_deploy":
                    target = dep["target"]
                    if target not in expanded:
                        to_process.append(target)

    # Find services for expanded set
    plan_services = []
    for name in expanded:
        svc = _find_service(reg, name)
        if svc:
            plan_services.append(svc)

    # Topological sort into stages
    # Stage 1: migrations
    # Stage 2: services that other services depend on (APIs, config)
    # Stage 3: everything else (frontends, workers, standalone)
    stage1 = []  # migrations
    stage2 = []  # depended-upon services
    stage3 = []  # leaf services

    # Find which services are depended upon by others in the plan
    # Only hard gates (required_before_*) should influence staging order
    depended_upon = set()
    for svc in plan_services:
        for dep in svc.get("depends_on", []):
            if dep.get("gate", "").startswith("required_before_"):
                depended_upon.add(dep["target"])

    for svc in plan_services:
        if svc.get("type") == "migrations":
            stage1.append(svc)
        elif svc["name"] in depended_upon:
            stage2.append(svc)
        else:
            stage3.append(svc)

    stages = []
    if stage1:
        stages.append({
            "stage": 1,
            "label": "Database migrations",
            "gate": "blocking — must complete before proceeding",
            "services": [{"name": s["name"], "type": s["type"],
                          "deploy": s.get("deploy", {}),
                          "in_change_set": s.get("repo") in repos}
                         for s in stage1],
        })
    if stage2:
        stages.append({
            "stage": 2,
            "label": "API and config services",
            "gate": "verify health before proceeding to stage 3",
            "services": [{"name": s["name"], "type": s["type"],
                          "deploy": s.get("deploy", {}),
                          "in_change_set": s.get("repo") in repos}
                         for s in stage2],
            "parallel": len(stage2) > 1,
        })
    if stage3:
        stages.append({
            "stage": len(stages) + 1,
            "label": "Frontends and workers",
            "gate": "final verification",
            "services": [{"name": s["name"], "type": s["type"],
                          "deploy": s.get("deploy", {}),
                          "in_change_set": s.get("repo") in repos}
                         for s in stage3],
            "parallel": len(stage3) > 1,
        })

    # Identify services added by dependency expansion (not in original change set)
    auto_included = expanded - affected_names

    return {
        "repos_changed": repos,
        "services_affected": sorted(affected_names),
        "auto_included_dependencies": sorted(auto_included),
        "stages": stages,
        "total_services": len(plan_services),
        "warnings": [
            f"'{name}' auto-included as required dependency (not in your change set)"
            for name in sorted(auto_included)
        ] if auto_included else [],
    }
