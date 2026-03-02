"""Smoke tests for the Click CLI."""

from click.testing import CliRunner

from railguey.cli import main


class TestCLI:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.2.0" in result.output

    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "status" in result.output
        assert "logs" in result.output
        assert "deploy" in result.output
        assert "serve" in result.output

    def test_status_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["status", "--help"])
        assert result.exit_code == 0
        assert "WORKSPACE" in result.output

    def test_logs_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["logs", "--help"])
        assert result.exit_code == 0
        assert "--lines" in result.output
        assert "--build" in result.output
        assert "--filter" in result.output

    def test_serve_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "MCP" in result.output

    def test_doctor_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "WORKSPACE" in result.output

    def test_deployments_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["deployments", "--help"])
        assert result.exit_code == 0
        assert "--limit" in result.output

    def test_unknown_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent"])
        assert result.exit_code != 0
