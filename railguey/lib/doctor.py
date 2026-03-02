"""Opinionated workspace audit for Railway deployment best practices."""

from pathlib import Path

from railguey.lib.token import _load_token
from railguey.lib.graphql import _gql, _resolve_project


async def doctor(workspace: str) -> dict:
    """Audit a workspace for Railway deployment best practices.

    4-point check:
      1. RAILWAY_TOKEN exists in .env.local
      2. .env.local is in .gitignore
      3. GitHub Actions deploy workflow exists
      4. No services linked to GitHub repos (brittle)
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

    # --- Check 3: GitHub Actions deploy workflow ---
    max_score += 1
    workflows_dir = ws / ".github" / "workflows"
    has_deploy_workflow = False
    if workflows_dir.is_dir():
        for f in workflows_dir.iterdir():
            if f.suffix in (".yml", ".yaml") and f.is_file():
                content = f.read_text()
                if "railway" in content.lower() and "RAILWAY_TOKEN" in content:
                    has_deploy_workflow = True
                    break
    if has_deploy_workflow:
        score += 1
        findings.append({
            "check": "CI/CD workflow",
            "status": "pass",
            "message": "GitHub Actions workflow found with RAILWAY_TOKEN",
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
    if has_token:
        token = _load_token(workspace)
        project = await _resolve_project(token)
        if "error" not in project:
            project_id = project.get("projectId")
            query = """
            query project($id: String!) {
              project(id: $id) {
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
                edges = result.get("project", {}).get("services", {}).get("edges", [])
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

    return {
        "score": f"{score}/{max_score}",
        "findings": findings,
        "healthy": score == max_score,
    }
