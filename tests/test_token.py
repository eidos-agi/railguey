"""Tests for token discovery from .env.local / .env files."""

import pytest

from railguey.lib.token import _load_token
from tests.helpers import write_file


class TestLoadToken:
    def test_reads_from_env_local(self, workspace):
        write_file(workspace / ".env.local", "RAILWAY_TOKEN=abc123\n")
        assert _load_token(str(workspace)) == "abc123"

    def test_falls_back_to_env(self, workspace):
        write_file(workspace / ".env", "RAILWAY_TOKEN=fallback-token\n")
        assert _load_token(str(workspace)) == "fallback-token"

    def test_env_local_takes_priority(self, workspace):
        write_file(workspace / ".env.local", "RAILWAY_TOKEN=local-wins\n")
        write_file(workspace / ".env", "RAILWAY_TOKEN=env-loses\n")
        assert _load_token(str(workspace)) == "local-wins"

    def test_strips_double_quotes(self, workspace):
        write_file(workspace / ".env.local", 'RAILWAY_TOKEN="quoted-token"\n')
        assert _load_token(str(workspace)) == "quoted-token"

    def test_strips_single_quotes(self, workspace):
        write_file(workspace / ".env.local", "RAILWAY_TOKEN='single-quoted'\n")
        assert _load_token(str(workspace)) == "single-quoted"

    def test_ignores_comments(self, workspace):
        write_file(
            workspace / ".env.local",
            "# This is a comment\n# RAILWAY_TOKEN=nope\nRAILWAY_TOKEN=real\n",
        )
        assert _load_token(str(workspace)) == "real"

    def test_ignores_blank_lines(self, workspace):
        write_file(
            workspace / ".env.local",
            "\n\n  \nRAILWAY_TOKEN=after-blanks\n",
        )
        assert _load_token(str(workspace)) == "after-blanks"

    def test_handles_other_vars(self, workspace):
        write_file(
            workspace / ".env.local",
            "DATABASE_URL=postgres://localhost\nRAILWAY_TOKEN=found-it\nOTHER=val\n",
        )
        assert _load_token(str(workspace)) == "found-it"

    def test_strips_whitespace(self, workspace):
        write_file(workspace / ".env.local", "  RAILWAY_TOKEN=  spaced  \n")
        assert _load_token(str(workspace)) == "spaced"

    def test_raises_when_no_files(self, workspace):
        with pytest.raises(ValueError, match="RAILWAY_TOKEN not found"):
            _load_token(str(workspace))

    def test_raises_when_token_missing_from_file(self, workspace):
        write_file(workspace / ".env.local", "OTHER_VAR=hello\n")
        with pytest.raises(ValueError, match="RAILWAY_TOKEN not found"):
            _load_token(str(workspace))

    def test_raises_when_token_empty(self, workspace):
        write_file(workspace / ".env.local", "RAILWAY_TOKEN=\n")
        with pytest.raises(ValueError, match="RAILWAY_TOKEN not found"):
            _load_token(str(workspace))

    def test_uuid_style_token(self, workspace):
        write_file(
            workspace / ".env.local",
            "RAILWAY_TOKEN=adefb6b1-ac23-4fa9-b8fd-08c9f8cfa52e\n",
        )
        assert _load_token(str(workspace)) == "adefb6b1-ac23-4fa9-b8fd-08c9f8cfa52e"

    def test_resolves_tilde_path(self, workspace):
        write_file(workspace / ".env.local", "RAILWAY_TOKEN=tilde-test\n")
        assert _load_token(str(workspace)) == "tilde-test"
