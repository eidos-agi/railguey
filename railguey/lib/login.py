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

import getpass
import os
import re
import subprocess
import webbrowser
from pathlib import Path

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
        raise ValueError("Token looks too short — Railway tokens are typically 30+ chars.")
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
            new_content = TOKEN_LINE_PATTERN.sub(f"RAILWAY_TOKEN={token}", existing, count=1)
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


def login(
    workspace: str,
    open_browser: bool = True,
    token: str | None = None,
    github_repo: str | None = None,
) -> dict:
    """Bootstrap RAILWAY_TOKEN for a workspace.

    Args:
        workspace: path to the project directory that will host .env.local.
        open_browser: if True (default), open the Railway tokens page so
            the user can mint a project token. Set False for headless use.
        token: optional pre-supplied token. If None (the secure default),
            prompts via getpass. If provided, used directly — this exists
            for CI/scripted callers and skips the prompt.
        github_repo: optional "owner/repo" string. If set, also pushes
            the token to that repo's Actions secrets via `gh secret set`.

    Returns:
        Result dict with keys: workspace, env_file, gitignore_updated,
        github_secret (if applicable). Includes "error" on failure
        (CLI's _output() exits non-zero on that key).
    """
    ws = Path(workspace).expanduser().resolve()
    if not ws.is_dir():
        return {"error": f"Workspace does not exist: {ws}"}

    if open_browser and token is None:
        try:
            webbrowser.open(RAILWAY_TOKEN_PAGE)
        except webbrowser.Error:
            pass  # user can navigate manually

    if token is None:
        # Masked input — never echoed to terminal, never in shell history
        token = getpass.getpass(
            f"Paste your Railway project token (hidden, see {PROJECT_TOKEN_DOC}): "
        ).strip()

    if not token:
        return {"error": "No token provided."}

    try:
        _validate_token(token)
    except ValueError as e:
        return {"error": str(e)}

    env_file = _write_token(ws, token)
    gitignore_updated = _ensure_gitignore(ws)

    result: dict = {
        "workspace": str(ws),
        "env_file": str(env_file),
        "gitignore_updated": gitignore_updated,
    }

    if github_repo:
        result["github_secret"] = _push_to_github_secret(github_repo, token)
        if not result["github_secret"].get("ok"):
            # Don't propagate as top-level error — the local write succeeded.
            # Caller can decide whether to retry the gh push.
            pass

    return result
