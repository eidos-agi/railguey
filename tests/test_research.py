"""Tests for railguey.lib.research — the ssh railway.new agent driver.

Mocks tmux + emux so no network / real session is needed.
"""

from railguey.lib import research as R


def test_research_reaches_prompt_and_returns_answer(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(R.time, "sleep", lambda _s: None)
    monkeypatch.setattr(R, "_tmux", lambda args, timeout=10: _ok())

    # First capture: still in the menu. Second: at the agent prompt.
    screens = iter(["Select a project", "Message the agent…"])
    monkeypatch.setattr(R, "_capture", lambda s, lines=200: next(screens, "Message the agent…"))

    # emux ask echoes the question then the answer; research() strips the echo.
    def fake_run(cmd, capture_output, text, timeout):
        return _proc(stdout="How do I deploy?\nUse railguey upload-source.\n")
    monkeypatch.setattr(R.subprocess, "run", fake_run)

    out = R.research("How do I deploy?")
    assert out["ok"] is True
    assert out["answer"] == "Use railguey upload-source."
    assert out["via"] == "ssh railway.new"


def test_research_missing_emux(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda name: None if name == "emux" else f"/usr/bin/{name}")
    out = R.research("anything")
    assert "error" in out and "emux" in out["error"]


def test_research_never_reaches_prompt(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(R.time, "sleep", lambda _s: None)
    monkeypatch.setattr(R, "_tmux", lambda args, timeout=10: _ok())
    monkeypatch.setattr(R, "_capture", lambda s, lines=200: "still loading…")
    out = R.research("q?")
    assert "error" in out and "prompt" in out["error"]


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def _ok():
    return _Proc(0, "", "")


def _proc(stdout="", returncode=0, stderr=""):
    return _Proc(returncode, stdout, stderr)
