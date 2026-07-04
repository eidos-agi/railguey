"""Product research via the Railway agent's own SSH TUI (`ssh railway.new`).

Railway ships an interactive agent at `ssh railway.new` that answers questions
about deploys, cron, logs, and its own product from the official docs. This
module drives that agent in a throwaway tmux session and returns its answer.

The actual "type a prompt, wait for the streaming TUI to stop changing, read the
reply" step is delegated to `emux ask` — emux's reusable primitive for talking
to another AI through its terminal UI. railguey just knows the railway.new menu
navigation; emux knows how to converse.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

_SESSION = "railguey-research"
# Strings that indicate we've reached the agent's free-text input.
_PROMPT_MARKERS = ("Message the agent", "Ask a question")


def _tmux(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=timeout)


def _capture(session: str, lines: int = 200) -> str:
    r = _tmux(["capture-pane", "-t", session, "-p", "-S", f"-{lines}"])
    return r.stdout if r.returncode == 0 else ""


def research(
    question: str,
    settle: float = 3.0,
    max_seconds: float = 90.0,
    keep_session: bool = False,
) -> dict[str, Any]:
    """Ask the Railway agent `question` via `ssh railway.new`; return its answer.

    Requires `tmux`, `ssh`, and `emux` on PATH. Spawns a fresh session, walks the
    menu to the agent prompt, delegates the Q&A to `emux ask`, and (unless
    keep_session) tears the session down.
    """
    for binary in ("tmux", "ssh", "emux"):
        if shutil.which(binary) is None:
            hint = " (install: `uv tool install emux`)" if binary == "emux" else ""
            return {"error": f"{binary} not found on PATH{hint}"}

    _tmux(["kill-session", "-t", _SESSION])  # clean slate if a prior run left one
    _tmux([
        "new-session", "-d", "-s", _SESSION, "-x", "210", "-y", "52",
        "ssh -o StrictHostKeyChecking=no railway.new",
    ])
    try:
        # The menu (Chat with the agent -> workspace -> project) has a variable
        # number of steps — the highlighted default is what we want at each one,
        # so poll and press Enter until the free-text prompt appears.
        reached = False
        for _ in range(8):
            time.sleep(2)
            screen = _capture(_SESSION)
            if any(m in screen for m in _PROMPT_MARKERS):
                reached = True
                break
            _tmux(["send-keys", "-t", _SESSION, "Enter"])  # accept highlighted item
        if not reached:
            return {"error": "could not reach the Railway agent prompt",
                    "last_screen": _capture(_SESSION)}

        # Hand off to emux's settle-based converse primitive. `--busy thinking`
        # stops emux from mistaking the agent's "thinking…" indicator for the reply.
        proc = subprocess.run(
            ["emux", "ask", _SESSION, question,
             "--settle", str(settle), "--max", str(max_seconds), "--busy", "thinking"],
            capture_output=True, text=True, timeout=max_seconds + 30,
        )
        # emux's reply delta includes the echoed prompt line — drop it and any
        # leftover busy indicator.
        reply_lines = [
            ln for ln in (proc.stdout or "").splitlines()
            if ln.strip() and ln.strip() != question.strip() and "thinking" not in ln.lower()
        ]
        answer = "\n".join(reply_lines).strip()
        if not answer:
            return {"error": "no answer from the Railway agent", "stderr": (proc.stderr or "").strip()}
        return {"ok": True, "question": question, "answer": answer, "via": "ssh railway.new"}
    finally:
        if not keep_session:
            _tmux(["kill-session", "-t", _SESSION])
