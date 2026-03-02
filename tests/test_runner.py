"""Tests for the subprocess runner with mocked CLI."""

import asyncio
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from server import _run_railway
from helpers import mock_railway_proc


class TestRunRailway:
    @pytest.mark.asyncio
    async def test_returns_error_when_cli_missing(self, workspace_with_token):
        with patch("server.shutil.which", return_value=None):
            result = await _run_railway(str(workspace_with_token), ["status"])
        assert "error" in result
        assert "Railway CLI not found" in result["error"]

    @pytest.mark.asyncio
    async def test_successful_command(self, workspace_with_token):
        proc = mock_railway_proc(stdout=b"service list output")
        with (
            patch("server.shutil.which", return_value="/usr/local/bin/railway"),
            patch("server.asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await _run_railway(str(workspace_with_token), ["status", "--json"])
        assert result == {"output": "service list output"}

    @pytest.mark.asyncio
    async def test_failed_command(self, workspace_with_token):
        proc = mock_railway_proc(stdout=b"", stderr=b"not authenticated", returncode=1)
        with (
            patch("server.shutil.which", return_value="/usr/local/bin/railway"),
            patch("server.asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await _run_railway(str(workspace_with_token), ["status"])
        assert "error" in result
        assert "exited 1" in result["error"]
        assert result["stderr"] == "not authenticated"

    @pytest.mark.asyncio
    async def test_timeout(self, workspace_with_token):
        async def slow_communicate():
            await asyncio.sleep(10)
            return b"", b""

        proc = AsyncMock()
        proc.communicate = slow_communicate

        with (
            patch("server.shutil.which", return_value="/usr/local/bin/railway"),
            patch("server.asyncio.create_subprocess_exec", return_value=proc),
        ):
            result = await _run_railway(str(workspace_with_token), ["logs"], timeout=0.1)
        assert "error" in result
        assert "timed out" in result["error"]

    @pytest.mark.asyncio
    async def test_injects_token_into_env(self, workspace_with_token):
        proc = mock_railway_proc()
        captured_kwargs = {}

        async def capture_exec(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return proc

        with (
            patch("server.shutil.which", return_value="/usr/local/bin/railway"),
            patch("server.asyncio.create_subprocess_exec", side_effect=capture_exec),
        ):
            await _run_railway(str(workspace_with_token), ["status"])
        assert captured_kwargs["env"]["RAILWAY_TOKEN"] == "test-token-123"

    @pytest.mark.asyncio
    async def test_sets_cwd_to_workspace(self, workspace_with_token):
        proc = mock_railway_proc()
        captured_kwargs = {}

        async def capture_exec(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return proc

        with (
            patch("server.shutil.which", return_value="/usr/local/bin/railway"),
            patch("server.asyncio.create_subprocess_exec", side_effect=capture_exec),
        ):
            await _run_railway(str(workspace_with_token), ["status"])
        expected = str(Path(str(workspace_with_token)).resolve())
        assert captured_kwargs["cwd"] == expected

    @pytest.mark.asyncio
    async def test_raises_on_missing_token(self, workspace):
        with pytest.raises(ValueError, match="RAILWAY_TOKEN not found"):
            await _run_railway(str(workspace), ["status"])
