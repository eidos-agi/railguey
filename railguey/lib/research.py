"""Product research via the Railway agent's own SSH TUI (`ssh railway.new`).

Railway ships an interactive agent at `ssh railway.new` that answers questions
about deploys, cron, logs, and its own product from the official docs. This
module drives that agent and returns its answer.

Two emux primitives do the work (emux = "talk to another AI through its TUI"):
- `emux navigate` — model-driven: reach the agent's chat prompt through the
  menu, letting a model pick keystrokes (handles reordering / new screens).
- `emux ask` — send a question, wait for the streamed reply to settle, return it.

The chat session is PERSISTENT across calls. The first `research()` connects and
navigates to the prompt; later calls reuse the SAME live session, so the agent
keeps the conversation context (follow-ups like "and for that service?" work).
Pass reset=True (or `railguey research --reset`) to start a fresh conversation.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from typing import Any

_SESSION = "railguey-research"
# Strings that indicate we're at the agent's free-text input.
_PROMPT_MARKERS = ("Message the agent", "Ask a question")
_NAV_GOAL = (
    "Reach the free-text chat input where I can type a question to the Railway "
    "agent (the screen shows 'Message the agent…' or 'Ask a question'). Choose "
    "the option about chatting with the agent. At any workspace or project "
    "picker, select the first / highlighted option."
)


def _tmux(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["tmux", *args], capture_output=True, text=True, timeout=timeout)


def _session_exists() -> bool:
    return _tmux(["has-session", "-t", _SESSION]).returncode == 0


def _capture(lines: int = 200) -> str:
    r = _tmux(["capture-pane", "-t", _SESSION, "-p", "-S", f"-{lines}"])
    return r.stdout if r.returncode == 0 else ""


def _at_prompt() -> bool:
    return any(m in _capture() for m in _PROMPT_MARKERS)


def research(
    question: str,
    settle: float = 3.0,
    max_seconds: float = 90.0,
    reset: bool = False,
    keep_session: bool = True,
) -> dict[str, Any]:
    """Ask the Railway agent `question` via `ssh railway.new`; return its answer.

    Reuses a persistent chat session so the agent keeps context across questions.
    Requires `tmux`, `ssh`, and `emux` on PATH.

    Args:
        question: What to ask the agent.
        settle: Seconds of an unchanged pane before the reply is considered done.
        max_seconds: Hard cap on waiting for a reply.
        reset: Tear down any existing chat and start a fresh conversation.
        keep_session: Leave the session alive after answering (default True) so
            the next call continues the same conversation. False closes it.
    """
    for binary in ("tmux", "ssh", "emux"):
        if shutil.which(binary) is None:
            hint = " (install: `uv tool install emux`)" if binary == "emux" else ""
            return {"error": f"{binary} not found on PATH{hint}"}

    if reset and _session_exists():
        _tmux(["kill-session", "-t", _SESSION])

    fresh = False
    if not _session_exists():
        fresh = True
        _tmux([
            "new-session", "-d", "-s", _SESSION, "-x", "210", "-y", "52",
            "ssh -o StrictHostKeyChecking=no railway.new",
        ])
        time.sleep(3)  # let the SSH TUI paint its first screen

    try:
        # Only navigate when we're not already at the prompt — a reused session
        # mid-conversation is already there, so we skip straight to asking (and
        # preserve context).
        if not _at_prompt():
            nav = subprocess.run(
                ["emux", "navigate", _SESSION, _NAV_GOAL,
                 "--until", _PROMPT_MARKERS[0], "--max-steps", "12"],
                capture_output=True, text=True, timeout=240,
            )
            if not _at_prompt():
                return {"error": "could not reach the Railway agent prompt",
                        "nav_stderr": (nav.stderr or "").strip(),
                        "last_screen": _capture()}

        # Ask via emux's settle-based converse; --busy thinking keeps the agent's
        # streaming indicator from being read back as the reply.
        proc = subprocess.run(
            ["emux", "ask", _SESSION, question,
             "--settle", str(settle), "--max", str(max_seconds), "--busy", "thinking"],
            capture_output=True, text=True, timeout=max_seconds + 30,
        )
        reply_lines = [
            ln for ln in (proc.stdout or "").splitlines()
            if ln.strip() and ln.strip() != question.strip() and "thinking" not in ln.lower()
        ]
        answer = "\n".join(reply_lines).strip()
        if not answer:
            return {"error": "no answer from the Railway agent", "stderr": (proc.stderr or "").strip()}
        return {
            "ok": True,
            "question": question,
            "answer": answer,
            "via": "ssh railway.new",
            "session": _SESSION,
            "new_conversation": fresh or reset,
        }
    finally:
        if not keep_session:
            _tmux(["kill-session", "-t", _SESSION])
