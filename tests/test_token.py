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
        with pytest.raises(ValueError, match="No project-scoped Railway token found"):
            _load_token(str(workspace))

    def test_raises_when_token_missing_from_file(self, workspace):
        write_file(workspace / ".env.local", "OTHER_VAR=hello\n")
        with pytest.raises(ValueError, match="No project-scoped Railway token found"):
            _load_token(str(workspace))

    def test_raises_when_token_empty(self, workspace):
        write_file(workspace / ".env.local", "RAILWAY_TOKEN=\n")
        with pytest.raises(ValueError, match="No project-scoped Railway token found"):
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


class TestSiblingDiscovery:
    """Fallback: a fresh workspace inherits the project token when ≥2
    sibling repos under the same parent already carry the same value."""

    def _sibling(self, parent, name, token, fname=".env.local"):
        write_file(parent / name / fname, f"RAILWAY_TOKEN={token}\n")

    def test_inherits_token_shared_by_two_siblings(self, workspace):
        parent = workspace.parent
        self._sibling(parent, "repo-a", "proj-token")
        self._sibling(parent, "repo-b", "proj-token")
        assert _load_token(str(workspace)) == "proj-token"

    def test_writes_inherited_token_to_env_local(self, workspace):
        parent = workspace.parent
        self._sibling(parent, "repo-a", "proj-token")
        self._sibling(parent, "repo-b", "proj-token")
        _load_token(str(workspace))
        body = (workspace / ".env.local").read_text()
        assert "RAILWAY_TOKEN=proj-token" in body
        assert "repo-a" in body and "repo-b" in body  # provenance comment

    def test_single_sibling_is_not_enough(self, workspace):
        self._sibling(workspace.parent, "repo-a", "lonely-token")
        with pytest.raises(ValueError, match="No project-scoped Railway token found"):
            _load_token(str(workspace))

    def test_majority_value_wins(self, workspace):
        parent = workspace.parent
        self._sibling(parent, "repo-a", "majority")
        self._sibling(parent, "repo-b", "majority")
        self._sibling(parent, "repo-c", "outlier")
        assert _load_token(str(workspace)) == "majority"

    def test_own_env_local_beats_siblings(self, workspace):
        parent = workspace.parent
        self._sibling(parent, "repo-a", "sibling-token")
        self._sibling(parent, "repo-b", "sibling-token")
        write_file(workspace / ".env.local", "RAILWAY_TOKEN=own-token\n")
        assert _load_token(str(workspace)) == "own-token"

    def test_reads_sibling_plain_env_files(self, workspace):
        parent = workspace.parent
        self._sibling(parent, "repo-a", "env-token", fname=".env")
        self._sibling(parent, "repo-b", "env-token", fname=".env")
        assert _load_token(str(workspace)) == "env-token"
