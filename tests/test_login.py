"""Tests for the login bootstrap command (railguey.lib.login).

The login flow is the bridge between Railway's dashboard (where tokens
are minted by humans) and railguey's workspace-scoped .env.local
(where every other railguey command reads from). These tests verify
the bridge is safe — no leaks, no overwrites of unrelated vars, and
correct .gitignore handling.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from railguey.lib import login as login_lib
from tests.helpers import write_file


VALID_TOKEN = "abcdef0123456789-railway-test-token-9876543210"
SHORT_TOKEN = "tooshort"
SPACE_TOKEN = "has space in it but is long enough to pass length check"


class TestValidateToken:
    def test_accepts_long_token(self):
        login_lib._validate_token(VALID_TOKEN)  # no raise

    def test_rejects_short(self):
        with pytest.raises(ValueError, match="too short"):
            login_lib._validate_token(SHORT_TOKEN)

    def test_rejects_whitespace(self):
        with pytest.raises(ValueError, match="whitespace"):
            login_lib._validate_token(SPACE_TOKEN)


class TestEnsureGitignore:
    def test_no_gitignore_returns_false(self, workspace):
        assert login_lib._ensure_gitignore(workspace) is False

    def test_already_has_env_local(self, workspace):
        write_file(workspace / ".gitignore", "node_modules/\n.env.local\n")
        assert login_lib._ensure_gitignore(workspace) is False

    def test_already_has_env_glob(self, workspace):
        write_file(workspace / ".gitignore", "node_modules/\n.env*\n")
        assert login_lib._ensure_gitignore(workspace) is False

    def test_adds_env_local_when_missing(self, workspace):
        write_file(workspace / ".gitignore", "node_modules/\n")
        assert login_lib._ensure_gitignore(workspace) is True
        contents = (workspace / ".gitignore").read_text()
        assert ".env.local" in contents


class TestWriteToken:
    def test_creates_envfile_when_missing(self, workspace):
        envfile = login_lib._write_token(workspace, VALID_TOKEN)
        assert envfile.read_text() == f"RAILWAY_TOKEN={VALID_TOKEN}\n"

    def test_replaces_existing_railway_token_line(self, workspace):
        write_file(
            workspace / ".env.local",
            "DATABASE_URL=postgres://x\nRAILWAY_TOKEN=old\nOTHER=keep\n",
        )
        login_lib._write_token(workspace, VALID_TOKEN)
        contents = (workspace / ".env.local").read_text()
        assert f"RAILWAY_TOKEN={VALID_TOKEN}" in contents
        assert "old" not in contents
        # Other vars must survive
        assert "DATABASE_URL=postgres://x" in contents
        assert "OTHER=keep" in contents

    def test_appends_when_other_vars_exist_but_no_railway_token(self, workspace):
        write_file(workspace / ".env.local", "DATABASE_URL=postgres://x\n")
        login_lib._write_token(workspace, VALID_TOKEN)
        contents = (workspace / ".env.local").read_text()
        assert "DATABASE_URL=postgres://x" in contents
        assert f"RAILWAY_TOKEN={VALID_TOKEN}" in contents

    def test_sets_restrictive_permissions(self, workspace):
        envfile = login_lib._write_token(workspace, VALID_TOKEN)
        # Skip on filesystems that don't support chmod (Windows in CI)
        if os.name == "posix":
            mode = stat.S_IMODE(envfile.stat().st_mode)
            assert mode == 0o600


class TestLoginIntegration:
    def test_login_with_explicit_token_writes_envfile(self, workspace):
        result = login_lib.login(
            workspace=str(workspace),
            open_browser=False,
            token=VALID_TOKEN,
            skip_validation=True,
        )
        assert "error" not in result
        assert result["env_file"] == str(workspace / ".env.local")
        assert (workspace / ".env.local").read_text() == f"RAILWAY_TOKEN={VALID_TOKEN}\n"

    def test_login_rejects_invalid_token(self, workspace):
        result = login_lib.login(
            workspace=str(workspace),
            open_browser=False,
            token=SHORT_TOKEN,
            skip_validation=True,
        )
        assert "error" in result
        assert not (workspace / ".env.local").exists()

    def test_login_rejects_missing_workspace(self, tmp_path):
        result = login_lib.login(
            workspace=str(tmp_path / "does-not-exist"),
            open_browser=False,
            token=VALID_TOKEN,
            skip_validation=True,
        )
        assert "error" in result

    def test_login_does_not_open_browser_when_token_supplied(self, workspace):
        with patch("railguey.lib.login.webbrowser.open") as opened:
            login_lib.login(
                workspace=str(workspace),
                open_browser=True,
                token=VALID_TOKEN,
                skip_validation=True,
            )
            assert opened.call_count == 0

    def test_login_patches_gitignore_when_present(self, workspace):
        write_file(workspace / ".gitignore", "node_modules/\n")
        result = login_lib.login(
            workspace=str(workspace),
            open_browser=False,
            token=VALID_TOKEN,
            skip_validation=True,
        )
        assert result["gitignore_updated"] is True
        assert ".env.local" in (workspace / ".gitignore").read_text()


class TestGitHubSecretPush:
    def test_token_passed_via_stdin_not_argv(self, workspace):
        """Critical: token must NEVER appear in subprocess args (visible to ps)."""
        captured = {}

        def fake_run(args, **kwargs):
            # The new login flow calls subprocess.run twice: once to
            # detect the git origin (no `input`), once to push the
            # secret to GitHub (with `input`). We only care about the
            # gh-secret-set call here.
            if isinstance(args, list) and "gh" in args and "secret" in args:
                captured["args"] = args
                captured["input"] = kwargs.get("input")

            class Result:
                returncode = 0
                stderr = ""
                stdout = ""

            return Result()

        with patch("railguey.lib.login.subprocess.run", side_effect=fake_run):
            login_lib.login(
                workspace=str(workspace),
                open_browser=False,
                token=VALID_TOKEN,
                github_repo="jetta-operating/labs",
                skip_validation=True,
            )

        # Token must be in stdin, not in args
        assert captured["input"] == VALID_TOKEN
        assert VALID_TOKEN not in " ".join(captured["args"])

    def test_gh_not_installed_returns_helpful_error_in_subkey(self, workspace):
        with patch(
            "railguey.lib.login.subprocess.run",
            side_effect=FileNotFoundError("gh not found"),
        ):
            result = login_lib.login(
                workspace=str(workspace),
                open_browser=False,
                token=VALID_TOKEN,
                github_repo="jetta-operating/labs",
                skip_validation=True,
            )
        # Local write succeeded — the gh failure is sub-keyed, not top-level
        assert "error" not in result
        assert result["github_secret"]["ok"] is False
        assert "gh CLI not installed" in result["github_secret"]["error"]
