"""Tests for railguey.lib.research — persistent, model-navigated agent driver.

Mocks tmux + emux so no network / real session is needed.
"""

from railguey.lib import research as R


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _base(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(R.time, "sleep", lambda _s: None)


def test_fresh_session_navigates_then_answers(monkeypatch):
    _base(monkeypatch)
    calls = {"has": 0}

    def fake_tmux(args, timeout=10):
        if args[0] == "has-session":
            calls["has"] += 1
            return _Proc(returncode=1)  # session does not exist -> fresh
        return _Proc(returncode=0)

    monkeypatch.setattr(R, "_tmux", fake_tmux)
    # Not at prompt until after navigate; then emux ask returns the answer.
    prompt_state = {"at": False}
    monkeypatch.setattr(R, "_capture", lambda lines=200: "Message the agent…" if prompt_state["at"] else "Select a project")

    def fake_run(cmd, capture_output, text, timeout):
        if cmd[1] == "navigate":
            prompt_state["at"] = True  # navigation reached the prompt
            return _Proc(stdout="reached (until) in 3 step(s)")
        # emux ask
        return _Proc(stdout="How do I deploy?\nUse railguey upload-source.\n")

    monkeypatch.setattr(R.subprocess, "run", fake_run)

    out = R.research("How do I deploy?")
    assert out["ok"] is True
    assert out["answer"] == "Use railguey upload-source."
    assert out["new_conversation"] is True


def test_reused_session_skips_navigation(monkeypatch):
    """A live session already at the prompt must NOT re-navigate (keeps context)."""
    _base(monkeypatch)
    monkeypatch.setattr(R, "_tmux", lambda args, timeout=10: _Proc(returncode=0))  # session exists
    monkeypatch.setattr(R, "_capture", lambda lines=200: "Message the agent…")  # already at prompt

    seen = {"navigate": False}

    def fake_run(cmd, capture_output, text, timeout):
        if cmd[1] == "navigate":
            seen["navigate"] = True
        return _Proc(stdout="and logs?\nUse railguey logs <svc>.\n")

    monkeypatch.setattr(R.subprocess, "run", fake_run)

    out = R.research("and logs?")
    assert out["ok"] is True
    assert seen["navigate"] is False  # reused conversation, no re-nav
    assert out["new_conversation"] is False


def test_missing_emux(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda name: None if name == "emux" else f"/usr/bin/{name}")
    out = R.research("anything")
    assert "error" in out and "emux" in out["error"]


def test_navigation_fails_to_reach_prompt(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(R, "_tmux", lambda args, timeout=10: _Proc(returncode=1))  # fresh each check
    monkeypatch.setattr(R, "_capture", lambda lines=200: "still loading…")  # never at prompt
    monkeypatch.setattr(R.subprocess, "run",
                        lambda cmd, capture_output, text, timeout: _Proc(stdout="", stderr="stalled"))
    out = R.research("q?")
    assert "error" in out and "prompt" in out["error"]
