"""Opinionated workspace audit for Railway deployment best practices."""

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
        run: railway up --service "$RAILWAY_SERVICE" --detach
"""


def _parse_workflow_details(workflows_dir: Path) -> dict:
    """Parse deploy workflow(s) for Railway-specific details.

    Returns:
        {
            "found": bool,
            "branches": list[str],          # branches that trigger deploys
            "environments": list[str],       # --environment flags referenced
            "services": list[str],           # --service flags referenced
            "file": str,                     # workflow filename
        }
    """
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

        # Parse YAML for branch triggers
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
            pass  # YAML parse failed — we still found the workflow

        # Scan for --environment flags in the raw text
        for line in content.splitlines():
            stripped = line.strip()
            if "--environment" in stripped:
                # Extract value after --environment (handles both = and space)
                for part in stripped.split():
                    if part.startswith("--environment="):
                        result["environments"].append(part.split("=", 1)[1])
                    elif part == "--environment":
                        # Next token is the value — find it
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

        # Deduplicate
        result["environments"] = sorted(set(result["environments"]))
        result["services"] = sorted(set(result["services"]))
        break  # Use first matching workflow

    return result


async def doctor(workspace: str) -> dict:
    """Audit a workspace for Railway deployment best practices.

    6-point check:
      1. RAILWAY_TOKEN exists in .env.local
      2. .env.local is in .gitignore
      3. GitHub Actions deploy workflow exists and covers all branches
      4. No services linked to GitHub repos (brittle)
      5. Token scope covers all environments referenced in workflow
      6. Workflow environment targets match real Railway environments
    """
    ws = Path(workspace).expanduser().resolve()
    findings = []
    score = 0
    max_score = 0

    # --- Check 1: RAILWAY_TOKEN exists ---
    max_score += 1
    has_token = False
    try:
        _load_token(workspace)
        has_token = True
        score += 1
        findings.append({
            "check": "RAILWAY_TOKEN",
            "status": "pass",
            "message": "Found in .env.local or .env",
        })
    except ValueError:
        findings.append({
            "check": "RAILWAY_TOKEN",
            "status": "fail",
            "message": "Not found. Add RAILWAY_TOKEN=<your-project-token> to .env.local",
            "fix": "Get a project token from Railway dashboard > Project > Settings > Tokens",
        })

    # --- Check 2: .env.local in .gitignore ---
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
        findings.append({
            "check": ".gitignore",
            "status": "pass",
            "message": ".env.local is gitignored",
        })
    else:
        findings.append({
            "check": ".gitignore",
            "status": "warn",
            "message": ".env.local may not be gitignored — token could leak",
            "fix": "Add .env.local to your .gitignore file",
        })

    # --- Check 3: GitHub Actions deploy workflow + branch coverage ---
    max_score += 1
    workflows_dir = ws / ".github" / "workflows"
    wf = _parse_workflow_details(workflows_dir)

    if wf["found"]:
        if len(wf["environments"]) > 1 and len(wf["branches"]) < len(wf["environments"]):
            # Workflow targets multiple environments but fewer branches trigger it
            findings.append({
                "check": "CI/CD workflow",
                "status": "warn",
                "message": (
                    f"Workflow targets {len(wf['environments'])} environment(s) "
                    f"({', '.join(wf['environments'])}) but only "
                    f"{len(wf['branches'])} branch(es) trigger it "
                    f"({', '.join(wf['branches']) or 'none detected'})"
                ),
                "fix": "Add all deployment branches to on.push.branches in the workflow",
            })
        elif len(wf["environments"]) > 1 and len(wf["branches"]) >= len(wf["environments"]):
            score += 1
            findings.append({
                "check": "CI/CD workflow",
                "status": "pass",
                "message": (
                    f"Deploy workflow covers {len(wf['branches'])} branch(es) "
                    f"({', '.join(wf['branches'])}) → "
                    f"{len(wf['environments'])} environment(s) "
                    f"({', '.join(wf['environments'])})"
                ),
            })
        elif len(wf["environments"]) <= 1:
            score += 1
            findings.append({
                "check": "CI/CD workflow",
                "status": "pass",
                "message": (
                    f"Deploy workflow found ({wf['file']})"
                    + (f", branches: {', '.join(wf['branches'])}" if wf["branches"] else "")
                ),
            })
    else:
        findings.append({
            "check": "CI/CD workflow",
            "status": "warn",
            "message": "No GitHub Actions deploy workflow found",
            "fix": (
                "Add .github/workflows/deploy.yml using the project token pattern. "
                "See: https://github.com/rhea-impact/railguey/tree/main/examples"
            ),
        })

    # --- Check 4: GitHub repo linking (check via GraphQL if token exists) ---
    max_score += 1
    railway_envs = {}  # {env_id: env_name} — populated if token works
    token_env_id = None

    if has_token:
        token = _load_token(workspace)
        project = await _resolve_project(token)
        if "error" not in project:
            project_id = project.get("projectId")
            token_env_id = project.get("environmentId")
            query = """
            query project($id: String!) {
              project(id: $id) {
                environments { edges { node { id name } } }
                services {
                  edges {
                    node { id name }
                  }
                }
              }
            }
            """
            result = await _gql(token, query, {"id": project_id})
            if "error" not in result:
                proj = result.get("project", {})
                railway_envs = {
                    e["node"]["id"]: e["node"]["name"]
                    for e in proj.get("environments", {}).get("edges", [])
                }
                edges = proj.get("services", {}).get("edges", [])
                linked_services = []
                for edge in edges:
                    svc = edge.get("node", {})
                    svc_id = svc.get("id")
                    svc_name = svc.get("name", "unknown")
                    svc_query = """
                    query service($id: String!) {
                      service(id: $id) { id name repoTriggers { repository branch } }
                    }
                    """
                    svc_result = await _gql(token, svc_query, {"id": svc_id})
                    if "error" not in svc_result:
                        triggers = svc_result.get("service", {}).get("repoTriggers", [])
                        if triggers:
                            linked_services.append({
                                "service": svc_name,
                                "repo": triggers[0].get("repository", "unknown"),
                            })

                if linked_services:
                    findings.append({
                        "check": "GitHub repo linking",
                        "status": "warn",
                        "message": f"{len(linked_services)} service(s) linked to GitHub repos (brittle auto-deploy)",
                        "linked": linked_services,
                        "fix": (
                            "Consider disconnecting with railguey_unlink_repo and using "
                            "GitHub Actions CI/CD instead. Repo linking has been unreliable."
                        ),
                    })
                else:
                    score += 1
                    findings.append({
                        "check": "GitHub repo linking",
                        "status": "pass",
                        "message": "No services linked to GitHub repos (good — using token-based deploys)",
                    })
            else:
                findings.append({
                    "check": "GitHub repo linking",
                    "status": "skip",
                    "message": "Could not query project (API error)",
                })
        else:
            findings.append({
                "check": "GitHub repo linking",
                "status": "skip",
                "message": "Could not resolve project from token",
            })
    else:
        findings.append({
            "check": "GitHub repo linking",
            "status": "skip",
            "message": "No token — cannot check repo linking",
        })

    # --- Check 5: Token scope vs workflow environment targets ---
    max_score += 1
    if has_token and token_env_id and wf["found"] and wf["environments"]:
        token_env_name = railway_envs.get(token_env_id, "unknown")
        workflow_envs = set(wf["environments"])
        # Token is scoped to one environment — warn if workflow targets others
        uncovered = workflow_envs - {token_env_name}
        if uncovered:
            findings.append({
                "check": "Token environment scope",
                "status": "fail",
                "message": (
                    f"Token is scoped to '{token_env_name}' but workflow also "
                    f"targets: {', '.join(sorted(uncovered))}. "
                    f"Deploys to those environments will fail with "
                    f"'Invalid project token for environment'"
                ),
                "fix": (
                    "Generate a project token that covers all environments, or add "
                    "separate GitHub secrets (e.g. RAILWAY_TOKEN_DEVELOP) per environment"
                ),
            })
        else:
            score += 1
            findings.append({
                "check": "Token environment scope",
                "status": "pass",
                "message": (
                    f"Token scoped to '{token_env_name}' — "
                    f"matches workflow target(s): {', '.join(sorted(workflow_envs))}"
                ),
            })
    elif has_token and wf["found"] and not wf["environments"]:
        # Workflow doesn't use --environment flag — single-environment setup, fine
        score += 1
        findings.append({
            "check": "Token environment scope",
            "status": "pass",
            "message": "Single-environment workflow — token scope is sufficient",
        })
    else:
        findings.append({
            "check": "Token environment scope",
            "status": "skip",
            "message": "Cannot verify — need both token and workflow with --environment flags",
        })

    # --- Check 6: Workflow environment names match Railway environments ---
    max_score += 1
    if wf["found"] and wf["environments"] and railway_envs:
        railway_env_names = set(railway_envs.values())
        workflow_envs = set(wf["environments"])
        invalid = workflow_envs - railway_env_names
        if invalid:
            findings.append({
                "check": "Environment names",
                "status": "fail",
                "message": (
                    f"Workflow references environment(s) not found in Railway: "
                    f"{', '.join(sorted(invalid))}. "
                    f"Railway has: {', '.join(sorted(railway_env_names))}"
                ),
                "fix": "Check --environment values in your workflow match Railway environment names exactly",
            })
        else:
            score += 1
            findings.append({
                "check": "Environment names",
                "status": "pass",
                "message": (
                    f"All workflow environments exist in Railway: "
                    f"{', '.join(sorted(workflow_envs))}"
                ),
            })
    elif wf["found"] and not wf["environments"]:
        score += 1
        findings.append({
            "check": "Environment names",
            "status": "pass",
            "message": "Single-environment workflow — no environment names to validate",
        })
    else:
        findings.append({
            "check": "Environment names",
            "status": "skip",
            "message": "Cannot verify — need workflow with --environment flags and Railway API access",
        })

    # --- Build remediation plan from findings ---
    remediation = []
    verify_after = []

    # Detect default branch and service name for templates
    default_branch = wf["branches"][0] if wf["branches"] else "main"
    service_names = wf["services"] if wf["services"] else []

    for f in findings:
        if f["status"] in ("pass", "skip"):
            continue

        if f["check"] == "RAILWAY_TOKEN":
            remediation.append({
                "intent": "Add Railway project token",
                "detail": "Get a project token from Railway dashboard > Project > Settings > Tokens",
                "file": ".env.local",
                "format": "RAILWAY_TOKEN=<your-project-token>",
                "suggested_tool": "railguey_variable_set or manual edit",
            })

        elif f["check"] == ".gitignore":
            remediation.append({
                "intent": "Protect .env.local from git",
                "detail": "Add .env.local to .gitignore to prevent token leak",
                "file": ".gitignore",
                "append_line": ".env.local",
                "suggested_tool": "Edit .gitignore",
            })

        elif f["check"] == "CI/CD workflow":
            remediation.append({
                "intent": "Create deploy workflow",
                "detail": f"GitHub Actions workflow that deploys to Railway on push to {default_branch}",
                "file": ".github/workflows/deploy.yml",
                "content": _WORKFLOW_TEMPLATE.format(branch=default_branch),
                "github_secret": {
                    "name": "RAILWAY_TOKEN",
                    "source": ".env.local key RAILWAY_TOKEN",
                },
                "github_variable": {
                    "name": "RAILWAY_SERVICE",
                    "value": service_names[0] if service_names else "<your-service-name>",
                },
                "suggested_tool": "Write workflow file, then gh secret set + gh variable set",
            })

        elif f["check"] == "GitHub repo linking":
            linked = f.get("linked", [])
            for svc in linked:
                remediation.append({
                    "intent": "Unlink service from GitHub repo",
                    "detail": f"Service '{svc['service']}' is linked to '{svc['repo']}' — brittle auto-deploy",
                    "service": svc["service"],
                    "suggested_tool": "railguey_unlink_repo",
                })

        elif f["check"] == "Token environment scope":
            remediation.append({
                "intent": "Fix token environment coverage",
                "detail": f["message"],
                "suggested_tool": "Generate a new project token from Railway dashboard, or use per-environment secrets",
            })

        elif f["check"] == "Environment names":
            remediation.append({
                "intent": "Fix workflow environment names",
                "detail": f["message"],
                "suggested_tool": "Edit workflow --environment flags to match Railway environment names",
            })

    # Verification steps (always included when remediation exists)
    if remediation:
        verify_after.append({
            "intent": "Confirm GitHub Actions deploy succeeded",
            "detail": "Check that the deploy workflow ran and completed successfully",
            "suggested_tool": "gh run list --limit 1",
        })
        verify_after.append({
            "intent": "Confirm Railway deployment landed",
            "detail": "Check that Railway received and completed the deployment",
            "suggested_tool": "railguey_deployments",
        })
        verify_after.append({
            "intent": "Re-run doctor to confirm all checks pass",
            "suggested_tool": "railguey_doctor",
        })

    result = {
        "score": f"{score}/{max_score}",
        "findings": findings,
        "healthy": score == max_score,
    }

    if remediation:
        result["remediation"] = remediation
    if verify_after:
        result["verify_after"] = verify_after

    return result
