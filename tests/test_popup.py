"""Tests for the popup module — focus on data-flow correctness without
actually rendering Tk widgets (CI runs headless).

Tk rendering is delegated to the terminal fallback in tests via
monkeypatching `_can_use_tk` to return False. The terminal fallback
itself is unit-tested with patched stdin/stdout.
"""

from __future__ import annotations

from unittest.mock import patch


from railguey.lib import popup


class TestCanUseTk:
    def test_returns_true_when_tkinter_imports(self):
        # On systems where tkinter is available (almost all dev machines)
        try:
            import tkinter  # noqa: F401
            assert popup._can_use_tk() is True
        except ImportError:
            assert popup._can_use_tk() is False


class TestTerminalPromptForToken:
    def test_returns_cancelled_when_no_tty(self):
        with patch("sys.stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            r = popup._terminal_prompt_for_token(
                railway_token_url="https://railway.app/account/tokens",
                default_token_name="gha-deploy",
                suggested_github_repo=None,
            )
        assert r.cancelled is True
        assert r.token == ""

    def test_uses_default_token_name_when_user_hits_enter(self):
        with patch("sys.stdin") as fake_stdin, \
             patch("getpass.getpass", return_value="abcdef0123456789-test-token-long-enough"), \
             patch("builtins.input", return_value=""):
            fake_stdin.isatty.return_value = True
            r = popup._terminal_prompt_for_token(
                railway_token_url="https://railway.app/account/tokens",
                default_token_name="gha-deploy",
                suggested_github_repo=None,
            )
        assert r.cancelled is False
        assert r.token == "abcdef0123456789-test-token-long-enough"
        assert r.token_name == "gha-deploy"
        assert r.push_to_github is False

    def test_accepts_user_supplied_name(self):
        with patch("sys.stdin") as fake_stdin, \
             patch("getpass.getpass", return_value="abcdef0123456789-test-token-long-enough"), \
             patch("builtins.input", return_value="custom-name"):
            fake_stdin.isatty.return_value = True
            r = popup._terminal_prompt_for_token(
                railway_token_url="https://railway.app/account/tokens",
                default_token_name="gha-deploy",
                suggested_github_repo=None,
            )
        assert r.token_name == "custom-name"

    def test_cancelled_on_empty_token(self):
        with patch("sys.stdin") as fake_stdin, \
             patch("getpass.getpass", return_value=""):
            fake_stdin.isatty.return_value = True
            r = popup._terminal_prompt_for_token(
                railway_token_url="https://railway.app/account/tokens",
                default_token_name="gha-deploy",
                suggested_github_repo=None,
            )
        assert r.cancelled is True


class TestTerminalConfirmSave:
    def test_confirms_when_user_presses_enter(self):
        with patch("sys.stdin") as fake_stdin, \
             patch("builtins.input", return_value=""):
            fake_stdin.isatty.return_value = True
            r = popup._terminal_confirm_save(
                project_name="x", project_id="p", environment_id="e",
                team_name="t", env_file_path="/tmp/.env.local", github_repo=None,
            )
        assert r.confirmed is True

    def test_confirms_when_user_types_y(self):
        with patch("sys.stdin") as fake_stdin, \
             patch("builtins.input", return_value="y"):
            fake_stdin.isatty.return_value = True
            r = popup._terminal_confirm_save(
                project_name="x", project_id="p", environment_id="e",
                team_name="t", env_file_path="/tmp/.env.local", github_repo=None,
            )
        assert r.confirmed is True

    def test_cancels_on_n(self):
        with patch("sys.stdin") as fake_stdin, \
             patch("builtins.input", return_value="n"):
            fake_stdin.isatty.return_value = True
            r = popup._terminal_confirm_save(
                project_name="x", project_id="p", environment_id="e",
                team_name="t", env_file_path="/tmp/.env.local", github_repo=None,
            )
        assert r.confirmed is False

    def test_non_interactive_defaults_to_confirmed(self):
        # When stdin isn't a TTY, the user has already explicitly chosen
        # to call login (often via CI). Confirming by default avoids a
        # silent hang.
        with patch("sys.stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            r = popup._terminal_confirm_save(
                project_name="x", project_id="p", environment_id="e",
                team_name="t", env_file_path="/tmp/.env.local", github_repo=None,
            )
        assert r.confirmed is True


class TestPromptDispatcher:
    def test_falls_back_to_terminal_when_tk_unavailable(self):
        with patch("railguey.lib.popup._can_use_tk", return_value=False), \
             patch("railguey.lib.popup._terminal_prompt_for_token") as fake:
            fake.return_value = popup.TokenPromptResult(
                token="x" * 30, token_name="gha-deploy",
                push_to_github=False, github_repo="", cancelled=False,
            )
            r = popup.prompt_for_token("https://railway.app/account/tokens")
            assert fake.called
            assert r.token == "x" * 30


class TestDetectGithubRepo:
    """The `_detect_github_repo` helper in login.py — placed here to keep
    the popup-adjacent helpers covered together."""

    def test_parses_ssh_url(self, tmp_path):
        from railguey.lib.login import _detect_github_repo
        from unittest.mock import patch as p

        class FakeResult:
            returncode = 0
            stdout = "git@github.com:jetta-operating/labs.git\n"
            stderr = ""

        with p("railguey.lib.login.subprocess.run", return_value=FakeResult()):
            assert _detect_github_repo(tmp_path) == "jetta-operating/labs"

    def test_parses_https_url(self, tmp_path):
        from railguey.lib.login import _detect_github_repo
        from unittest.mock import patch as p

        class FakeResult:
            returncode = 0
            stdout = "https://github.com/jetta-operating/jetta-intelligence-dot-com\n"
            stderr = ""

        with p("railguey.lib.login.subprocess.run", return_value=FakeResult()):
            assert _detect_github_repo(tmp_path) == "jetta-operating/jetta-intelligence-dot-com"

    def test_returns_none_when_no_remote(self, tmp_path):
        from railguey.lib.login import _detect_github_repo
        from unittest.mock import patch as p

        class FakeResult:
            returncode = 1
            stdout = ""
            stderr = "no remote"

        with p("railguey.lib.login.subprocess.run", return_value=FakeResult()):
            assert _detect_github_repo(tmp_path) is None

    def test_returns_none_when_git_not_installed(self, tmp_path):
        from railguey.lib.login import _detect_github_repo
        from unittest.mock import patch as p

        with p("railguey.lib.login.subprocess.run", side_effect=FileNotFoundError()):
            assert _detect_github_repo(tmp_path) is None
