"""Smoke tests for the Click CLI."""

from click.testing import CliRunner

from railguey import __version__
from railguey.cli import main


class TestCLI:
    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

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

    def test_redeploy_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["redeploy", "--help"])
        assert result.exit_code == 0
        assert "WORKSPACE" in result.output
        assert "SERVICE" in result.output

    def test_restart_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["restart", "--help"])
        assert result.exit_code == 0
        assert "WORKSPACE" in result.output

    def test_domain_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["domain", "--help"])
        assert result.exit_code == 0
        assert "--port" in result.output

    def test_rollback_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["rollback", "--help"])
        assert result.exit_code == 0
        assert "DEPLOYMENT_ID" in result.output

    def test_variables_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["variables", "--help"])
        assert result.exit_code == 0
        assert "SERVICE" in result.output

    def test_variable_set_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["variable-set", "--help"])
        assert result.exit_code == 0
        assert "KEY" in result.output
        assert "VALUE" in result.output

    def test_deployment_logs_help(self):
        runner = CliRunner()
        result = runner.invoke(main, ["deployment-logs", "--help"])
        assert result.exit_code == 0
        assert "DEPLOYMENT_ID" in result.output
        assert "--limit" in result.output
        assert "--build" in result.output
        assert "--filter" in result.output

    def test_all_commands_listed(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        expected = [
            "status", "logs", "deploy", "redeploy", "restart",
            "variables", "variable-set", "domain", "deployments",
            "rollback", "service-info", "http-logs", "deployment-logs",
            "unlink-repo", "environment-create", "doctor", "serve",
        ]
        for cmd in expected:
            assert cmd in result.output, f"Missing command: {cmd}"

    def test_unknown_command(self):
        runner = CliRunner()
        result = runner.invoke(main, ["nonexistent"])
        assert result.exit_code != 0
