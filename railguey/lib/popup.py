"""OS-agnostic popup dialogs for sensitive token entry and confirmation.

Why a popup instead of a terminal prompt?
- Tokens shouldn't pass through shell history, terminal scrollback, or
  paste-buffer trails that AI assistants and screenshot tools can scrape.
- Some users invoke railguey from non-interactive launchers (Raycast,
  Alfred, IDE tasks) where stdin isn't a real TTY.
- Confirmation steps deserve a real UI — read this, edit that, click OK.

The popup is cross-platform via Tk (Python stdlib). Tk ships with the
official python.org installer on macOS and Windows, and is installable
on every major Linux distro. When Tk isn't available, we degrade
gracefully to the existing getpass terminal flow so railguey never gets
stuck on a missing GUI.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class TokenPromptResult:
    """User's response to the token-entry popup."""

    token: str
    token_name: str
    push_to_github: bool
    github_repo: str
    cancelled: bool = False


@dataclass
class ConfirmPromptResult:
    """User's response to the post-validation confirmation popup."""

    confirmed: bool
    cancelled: bool = False


def prompt_for_token(
    railway_token_url: str,
    default_token_name: str = "gha-deploy",
    suggested_github_repo: str | None = None,
) -> TokenPromptResult:
    """Open a popup asking the user to paste a Railway token + adjust settings.

    Returns a TokenPromptResult. If the user closes the popup without
    submitting, `cancelled` is True (and other fields are empty).

    Falls back to a terminal getpass flow when Tk isn't available.
    """
    if _can_use_tk():
        try:
            return _tk_prompt_for_token(
                railway_token_url=railway_token_url,
                default_token_name=default_token_name,
                suggested_github_repo=suggested_github_repo or "",
            )
        except Exception:
            # Any Tk failure (missing display, screen lock, etc.) → terminal fallback
            pass
    return _terminal_prompt_for_token(
        railway_token_url=railway_token_url,
        default_token_name=default_token_name,
        suggested_github_repo=suggested_github_repo,
    )


def confirm_save(
    project_name: str,
    project_id: str,
    environment_id: str,
    team_name: str | None,
    env_file_path: str,
    github_repo: str | None,
) -> ConfirmPromptResult:
    """Show project metadata + write plan, ask user to confirm.

    Returns a ConfirmPromptResult. Falls back to terminal when Tk
    isn't available.
    """
    if _can_use_tk():
        try:
            return _tk_confirm_save(
                project_name=project_name,
                project_id=project_id,
                environment_id=environment_id,
                team_name=team_name,
                env_file_path=env_file_path,
                github_repo=github_repo,
            )
        except Exception:
            pass
    return _terminal_confirm_save(
        project_name=project_name,
        project_id=project_id,
        environment_id=environment_id,
        team_name=team_name,
        env_file_path=env_file_path,
        github_repo=github_repo,
    )


# ---------------------------------------------------------------------------
# Tk implementation
# ---------------------------------------------------------------------------


def _can_use_tk() -> bool:
    """Check if Tk is importable and a display is available."""
    try:
        import tkinter  # noqa: F401
    except ImportError:
        return False
    # On Linux, Tk imports fine but Tk() fails without DISPLAY.
    # Defer that check to the actual constructor call (caught above).
    return True


def _tk_prompt_for_token(
    railway_token_url: str,
    default_token_name: str,
    suggested_github_repo: str,
) -> TokenPromptResult:
    import tkinter as tk
    from tkinter import ttk

    result = TokenPromptResult(
        token="", token_name=default_token_name, push_to_github=False, github_repo="", cancelled=True
    )

    root = tk.Tk()
    root.title("railguey login")
    root.resizable(False, False)
    # Bring window forward across platforms
    root.lift()
    root.attributes("-topmost", True)
    root.after_idle(root.attributes, "-topmost", False)

    pad = {"padx": 12, "pady": 6}

    # Header
    ttk.Label(
        root,
        text="Bootstrap a Railway project token",
        font=("TkDefaultFont", 13, "bold"),
    ).grid(row=0, column=0, columnspan=2, sticky="w", **pad)

    ttk.Label(
        root,
        text=(
            "1. Open the Railway dashboard (already opened in your browser).\n"
            "2. Project → Settings → Tokens → Create Token.\n"
            "3. Copy the token, then paste below."
        ),
        justify="left",
    ).grid(row=1, column=0, columnspan=2, sticky="w", **pad)

    ttk.Label(root, text="Token URL:").grid(row=2, column=0, sticky="e", **pad)
    url_entry = ttk.Entry(root, width=50)
    url_entry.insert(0, railway_token_url)
    url_entry.configure(state="readonly")
    url_entry.grid(row=2, column=1, sticky="we", **pad)

    # Token name (editable, defaults provided)
    ttk.Label(root, text="Token name (for your reference):").grid(row=3, column=0, sticky="e", **pad)
    name_var = tk.StringVar(value=default_token_name)
    ttk.Entry(root, textvariable=name_var, width=50).grid(row=3, column=1, sticky="we", **pad)

    # Token (masked)
    ttk.Label(root, text="Paste token (hidden):").grid(row=4, column=0, sticky="e", **pad)
    token_var = tk.StringVar()
    token_entry = ttk.Entry(root, textvariable=token_var, show="•", width=50)
    token_entry.grid(row=4, column=1, sticky="we", **pad)
    token_entry.focus_set()

    # GitHub push checkbox + repo entry
    push_var = tk.BooleanVar(value=bool(suggested_github_repo))
    ttk.Checkbutton(
        root,
        text="Also push to GitHub Actions secret (RAILWAY_TOKEN)",
        variable=push_var,
    ).grid(row=5, column=0, columnspan=2, sticky="w", **pad)

    ttk.Label(root, text="GitHub repo (owner/repo):").grid(row=6, column=0, sticky="e", **pad)
    repo_var = tk.StringVar(value=suggested_github_repo)
    ttk.Entry(root, textvariable=repo_var, width=50).grid(row=6, column=1, sticky="we", **pad)

    # Buttons
    btn_frame = ttk.Frame(root)
    btn_frame.grid(row=7, column=0, columnspan=2, sticky="e", **pad)

    def on_ok():
        result.token = token_var.get().strip()
        result.token_name = name_var.get().strip() or default_token_name
        result.push_to_github = bool(push_var.get())
        result.github_repo = repo_var.get().strip()
        result.cancelled = False
        root.destroy()

    def on_cancel():
        result.cancelled = True
        root.destroy()

    ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right", padx=4)
    ttk.Button(btn_frame, text="Continue", command=on_ok).pack(side="right", padx=4)

    # Submit on Enter from the token field
    token_entry.bind("<Return>", lambda _e: on_ok())
    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()

    return result


def _tk_confirm_save(
    project_name: str,
    project_id: str,
    environment_id: str,
    team_name: str | None,
    env_file_path: str,
    github_repo: str | None,
) -> ConfirmPromptResult:
    import tkinter as tk
    from tkinter import ttk

    result = ConfirmPromptResult(confirmed=False, cancelled=True)

    root = tk.Tk()
    root.title("railguey login — confirm")
    root.resizable(False, False)
    root.lift()
    root.attributes("-topmost", True)
    root.after_idle(root.attributes, "-topmost", False)

    pad = {"padx": 12, "pady": 6}

    ttk.Label(
        root,
        text="Confirm — token validated against Railway",
        font=("TkDefaultFont", 13, "bold"),
    ).grid(row=0, column=0, columnspan=2, sticky="w", **pad)

    rows = [
        ("Project name", project_name),
        ("Project ID", project_id),
        ("Environment ID", environment_id),
        ("Team", team_name or "—"),
        ("Local file", env_file_path),
        ("GitHub repo", github_repo or "(skip)"),
    ]
    for i, (label, value) in enumerate(rows, start=1):
        ttk.Label(root, text=f"{label}:").grid(row=i, column=0, sticky="e", **pad)
        # Use a readonly Entry so users can copy values out for verification
        v_entry = ttk.Entry(root, width=55)
        v_entry.insert(0, value)
        v_entry.configure(state="readonly")
        v_entry.grid(row=i, column=1, sticky="we", **pad)

    ttk.Label(
        root,
        text="Click Save to write .env.local and (if selected) the GitHub secret.",
        foreground="#444",
    ).grid(row=len(rows) + 1, column=0, columnspan=2, sticky="w", **pad)

    btn_frame = ttk.Frame(root)
    btn_frame.grid(row=len(rows) + 2, column=0, columnspan=2, sticky="e", **pad)

    def on_save():
        result.confirmed = True
        result.cancelled = False
        root.destroy()

    def on_cancel():
        result.cancelled = True
        result.confirmed = False
        root.destroy()

    ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side="right", padx=4)
    ttk.Button(btn_frame, text="Save", command=on_save).pack(side="right", padx=4)

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()

    return result


# ---------------------------------------------------------------------------
# Terminal fallbacks
# ---------------------------------------------------------------------------


def _terminal_prompt_for_token(
    railway_token_url: str,
    default_token_name: str,
    suggested_github_repo: str | None,
) -> TokenPromptResult:
    import getpass

    if not sys.stdin.isatty():
        return TokenPromptResult(
            token="",
            token_name=default_token_name,
            push_to_github=False,
            github_repo="",
            cancelled=True,
        )

    print(f"Open this URL in your browser to mint a token: {railway_token_url}")
    print("(railguey would normally show a popup — Tk isn't available, falling back to terminal.)")
    token = getpass.getpass("Paste token (hidden): ").strip()
    if not token:
        return TokenPromptResult(
            token="",
            token_name=default_token_name,
            push_to_github=False,
            github_repo="",
            cancelled=True,
        )

    name_input = input(f"Token name [{default_token_name}]: ").strip()
    token_name = name_input or default_token_name

    push_repo = ""
    if suggested_github_repo:
        push_input = input(
            f"Also push to GitHub Actions secret on '{suggested_github_repo}'? [y/N]: "
        ).strip().lower()
        if push_input == "y":
            push_repo = suggested_github_repo

    return TokenPromptResult(
        token=token,
        token_name=token_name,
        push_to_github=bool(push_repo),
        github_repo=push_repo,
        cancelled=False,
    )


def _terminal_confirm_save(
    project_name: str,
    project_id: str,
    environment_id: str,
    team_name: str | None,
    env_file_path: str,
    github_repo: str | None,
) -> ConfirmPromptResult:
    if not sys.stdin.isatty():
        # Non-interactive: confirm by default — the user provided the token,
        # they meant to save it. Bail-out is via not providing a token.
        return ConfirmPromptResult(confirmed=True, cancelled=False)

    print()
    print("Token validated against Railway. Review:")
    print(f"  Project:       {project_name}  ({project_id})")
    print(f"  Environment:   {environment_id}")
    print(f"  Team:          {team_name or '—'}")
    print(f"  Local file:    {env_file_path}")
    print(f"  GitHub repo:   {github_repo or '(skip)'}")
    answer = input("Save? [Y/n]: ").strip().lower()
    confirmed = answer in ("", "y", "yes")
    return ConfirmPromptResult(confirmed=confirmed, cancelled=not confirmed)
