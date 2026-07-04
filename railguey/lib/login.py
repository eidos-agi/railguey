"""Bootstrap RAILWAY_TOKEN into a workspace's .env.local.

The bootstrap step (Railway dashboard → token → .env.local) was the one
manual gap in railguey's CLI-only workflow. This module fills that gap
by guiding the user through token creation and writing it without ever
echoing it back in the terminal or shell history.

Design notes:
- Token is read via getpass (masked input) — never appears in terminal
  output, shell history, process list, or chat transcripts.
- Browser auto-opens to the Railway tokens page so the user doesn't
  have to remember the URL.
- .gitignore is checked and patched if needed so the token cannot be
  committed by accident.
- Optional GitHub Actions secret push runs `gh secret set` with the
  token piped via stdin — not as a CLI argument — so it cannot be seen
  by `ps` or anything else watching the process table.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import webbrowser
from pathlib import Path

from railguey.lib import popup
from railguey.lib.graphql import _resolve_project_metadata

RAILWAY_TOKEN_PAGE = "https://railway.app/account/tokens"
PROJECT_TOKEN_DOC = "https://docs.railway.com/reference/project#tokens"
TOKEN_LINE_PATTERN = re.compile(r"^RAILWAY_TOKEN\s*=.*$", re.MULTILINE)


def _validate_token(token: str) -> None:
    """Light sanity check — Railway tokens are 30+ char hex/dash strings.

    We do NOT round-trip the token to Railway here; the caller can run
    `railguey status` after to verify connectivity. The point of this
    check is to catch accidental empty paste / common typos, not to
    authenticate.
    """
    if len(token) < 20:
        raise ValueError(
            "Token looks too short — Railway tokens are typically 30+ chars."
        )
    if any(c.isspace() for c in token):
        raise ValueError("Token contains whitespace — likely a paste error.")


def _ensure_gitignore(workspace: Path) -> bool:
    """Ensure workspace/.gitignore excludes .env.local.

    Returns True if .gitignore was modified, False if already correct
    or no .gitignore exists.
    """
    gitignore = workspace / ".gitignore"
    if not gitignore.is_file():
        return False
    content = gitignore.read_text()
    # Match either ".env.local" on its own line or as part of ".env*" / ".env.*"
    if re.search(r"^\s*\.env\.local\s*$", content, re.MULTILINE):
        return False
    if re.search(r"^\s*\.env\*\s*$", content, re.MULTILINE):
        return False
    if re.search(r"^\s*\.env\.\*\s*$", content, re.MULTILINE):
        return False
    # Append .env.local
    new_content = content.rstrip() + "\n.env.local\n"
    gitignore.write_text(new_content)
    return True


def _write_token(workspace: Path, token: str) -> Path:
    """Write or update RAILWAY_TOKEN in workspace/.env.local.

    Preserves any other vars already in the file. Writes with restrictive
    permissions (0o600) so other users on the machine can't read it.
    """
    envfile = workspace / ".env.local"
    new_line = f"RAILWAY_TOKEN={token}\n"
    if envfile.is_file():
        existing = envfile.read_text()
        if TOKEN_LINE_PATTERN.search(existing):
            # Replace the existing line
            new_content = TOKEN_LINE_PATTERN.sub(
                f"RAILWAY_TOKEN={token}", existing, count=1
            )
            # Ensure the replaced line still terminates with newline
            if not new_content.endswith("\n"):
                new_content += "\n"
            envfile.write_text(new_content)
        else:
            # Append, ensuring trailing newline
            sep = "" if existing.endswith("\n") or existing == "" else "\n"
            envfile.write_text(existing + sep + new_line)
    else:
        envfile.write_text(new_line)
    # Restrict permissions: only the user can read/write
    try:
        os.chmod(envfile, 0o600)
    except OSError:
        # Non-fatal on filesystems that don't support chmod (Windows, etc.)
        pass
    return envfile


def _push_to_github_secret(repo: str, token: str) -> dict:
    """Push token to a GitHub Actions repo secret via `gh secret set`.

    The token is piped to gh via stdin — never passed on the command
    line — so it cannot appear in `ps` output or shell history.
    """
    try:
        result = subprocess.run(
            ["gh", "secret", "set", "RAILWAY_TOKEN", "--repo", repo],
            input=token,
            text=True,
            capture_output=True,
            check=False,
            timeout=15,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error": "gh CLI not installed. Install with `brew install gh` (macOS) or see https://cli.github.com.",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "gh secret set timed out after 15s"}
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip() or "gh secret set failed"}
    return {"ok": True, "repo": repo}


def _detect_github_repo(workspace: Path) -> str | None:
    """Try to infer 'owner/repo' from the workspace's git origin URL.

    Returns None if no git origin is configured, the URL doesn't match
    a recognized GitHub form, or git isn't installed.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(workspace), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    # SSH form: git@github.com:owner/repo.git
    m = re.match(r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    # HTTPS form: https://github.com/owner/repo(.git)?
    m = re.match(r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?$", url)
    if m:
        return m.group(1)
    return None


def login(
    workspace: str,
    open_browser: bool = True,
    token: str | None = None,
    github_repo: str | None = None,
    use_popup: bool = True,
    skip_validation: bool = False,
) -> dict:
    """Bootstrap RAILWAY_TOKEN for a workspace.

    Default flow (interactive human use):
      1. Open the Railway tokens page in the user's default browser.
      2. Show a popup (Tk; falls back to terminal if Tk unavailable)
         with fields for the token, an editable token name, and an
         optional GitHub repo to also push the secret to.
      3. Validate the token by introspecting the project metadata
         from Railway's GraphQL API.
      4. Show a second popup confirming project name, project ID,
         environment ID, team, and the local + GitHub destinations.
      5. On confirm, write to .env.local with 0600 perms, patch
         .gitignore, and (optionally) push to GitHub Actions.

    Headless flow (CI / scripts):
      Pass token=<value>, optionally github_repo=<owner/repo>.
      use_popup=False also forces the terminal flow.

    Args:
        workspace: path to the project directory that will host .env.local.
        open_browser: if True (default), open the Railway tokens page so
            the user can mint a project token. Set False for headless use.
        token: optional pre-supplied token. If None (the secure default),
            prompts via popup or terminal.
        github_repo: optional "owner/repo" string. If set, also pushes
            the token to that repo's Actions secrets via `gh secret set`.
            If None, railguey tries to auto-detect from git origin and
            offers it in the popup as the default suggestion.
        use_popup: if True (default), use the GUI popup flow when
            available. Set False to force terminal-only.
        skip_validation: if True, skip the Railway API round-trip used
            to fetch project metadata. Useful in tests and offline use.

    Returns:
        Result dict with keys: workspace, env_file, gitignore_updated,
        token_name, project (metadata), github_secret (if applicable).
        Includes "error" on failure (CLI's _output() exits non-zero
        on that key).
    """
    ws = Path(workspace).expanduser().resolve()
    if not ws.is_dir():
        return {"error": f"Workspace does not exist: {ws}"}

    if open_browser and token is None:
        try:
            webbrowser.open(RAILWAY_TOKEN_PAGE)
        except webbrowser.Error:
            pass

    detected_repo = _detect_github_repo(ws)
    suggested_repo = github_repo or detected_repo
    token_name = "gha-deploy"

    if token is None:
        if use_popup:
            prompt = popup.prompt_for_token(
                railway_token_url=RAILWAY_TOKEN_PAGE,
                default_token_name=token_name,
                suggested_github_repo=suggested_repo,
            )
        else:
            prompt = popup._terminal_prompt_for_token(
                railway_token_url=RAILWAY_TOKEN_PAGE,
                default_token_name=token_name,
                suggested_github_repo=suggested_repo,
            )
        if prompt.cancelled or not prompt.token:
            return {"error": "Cancelled — no token saved."}
        token = prompt.token
        token_name = prompt.token_name
        if prompt.push_to_github and prompt.github_repo:
            github_repo = prompt.github_repo
        elif not prompt.push_to_github:
            github_repo = None

    try:
        _validate_token(token)
    except ValueError as e:
        return {"error": str(e)}

    project_meta: dict = {}
    if not skip_validation:
        try:
            project_meta = asyncio.run(_resolve_project_metadata(token))
        except Exception as e:
            project_meta = {"error": f"metadata lookup failed: {e}"}
        if "error" in project_meta:
            # Don't write a token we couldn't validate against Railway —
            # the whole point of confirmation is to catch bad pastes.
            return {
                "error": (
                    f"Token failed to validate against Railway: "
                    f"{project_meta.get('error')}. Nothing written."
                )
            }

    if use_popup and not skip_validation and project_meta:
        confirm = popup.confirm_save(
            project_name=project_meta.get("projectName") or "(unknown)",
            project_id=project_meta.get("projectId") or "(unknown)",
            environment_id=project_meta.get("environmentId") or "(unknown)",
            team_name=project_meta.get("teamName"),
            env_file_path=str(ws / ".env.local"),
            github_repo=github_repo,
        )
        if not confirm.confirmed:
            return {"error": "Cancelled at confirmation step. Nothing written."}

    env_file = _write_token(ws, token)
    gitignore_updated = _ensure_gitignore(ws)

    result: dict = {
        "workspace": str(ws),
        "env_file": str(env_file),
        "gitignore_updated": gitignore_updated,
        "token_name": token_name,
        "project": project_meta if project_meta else None,
    }

    if github_repo:
        result["github_secret"] = _push_to_github_secret(github_repo, token)

    return result
