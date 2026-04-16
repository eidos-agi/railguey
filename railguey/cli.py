"""CLI interface — Click commands that delegate to railguey.lib.tools.

Usage:
    railguey status /path/to/workspace
    railguey logs /path/to/workspace cerebro --lines 50
    railguey serve  # starts the MCP server
"""

import asyncio
import json

import click

from railguey import __version__
from railguey.lib import tools


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _output(result: dict):
    """Pretty-print a tool result as JSON."""
    click.echo(json.dumps(result, indent=2))


@click.group()
@click.version_option(version=__version__, prog_name="railguey")
def main():
    """railguey — project-scoped Railway management CLI."""


# ---------------------------------------------------------------------------
# CLI-backed commands
# ---------------------------------------------------------------------------


@main.command()
@click.argument("workspace")
def status(workspace):
    """Show status of all services in the Railway project."""
    _output(_run(tools.status(workspace)))


@main.command()
@click.argument("workspace")
@click.argument("service")
@click.option("--lines", default=100, help="Number of log lines to return.")
@click.option("--build", is_flag=True, help="Show build logs instead of deploy logs.")
@click.option("--filter", "filter_str", default=None, help="Filter log lines.")
def logs(workspace, service, lines, build, filter_str):
    """Fetch recent logs from a Railway service."""
    _output(_run(tools.logs(workspace, service, lines, build, filter_str)))


@main.command()
@click.argument("workspace")
@click.argument("service")
def deploy(workspace, service):
    """Trigger a deploy for a Railway service (non-blocking)."""
    _output(_run(tools.deploy(workspace, service)))


@main.command()
@click.argument("workspace")
@click.argument("service")
def variables(workspace, service):
    """List environment variables for a Railway service."""
    _output(_run(tools.variables(workspace, service)))


@main.command("variable-set")
@click.argument("workspace")
@click.argument("service")
@click.argument("key")
@click.argument("value")
def variable_set(workspace, service, key, value):
    """Set an environment variable on a Railway service."""
    _output(_run(tools.variable_set(workspace, service, key, value)))


@main.command()
@click.argument("workspace")
def services(workspace):
    """List all services in the Railway project."""
    _output(_run(tools.services(workspace)))


@main.command()
@click.argument("workspace")
@click.argument("service")
def redeploy(workspace, service):
    """Redeploy the latest deployment (rebuilds from source)."""
    _output(_run(tools.redeploy(workspace, service)))


@main.command()
@click.argument("workspace")
@click.argument("service")
def restart(workspace, service):
    """Restart the latest deployment (no rebuild)."""
    _output(_run(tools.restart(workspace, service)))


@main.command()
@click.argument("workspace")
@click.argument("service")
@click.option("--domain", "custom_domain", default=None, help="Custom domain to add.")
@click.option("--port", default=None, type=int, help="Port to bind the domain to.")
def domain(workspace, service, custom_domain, port):
    """Generate or add a domain to a service."""
    _output(_run(tools.domain(workspace, service, custom_domain, port)))


@main.command("environment-create")
@click.argument("workspace")
@click.argument("name")
def environment_create(workspace, name):
    """Create a new environment in the Railway project."""
    _output(_run(tools.environment_create(workspace, name)))


# ---------------------------------------------------------------------------
# GraphQL-backed commands
# ---------------------------------------------------------------------------


@main.command()
@click.argument("workspace")
@click.argument("service")
@click.option("--limit", default=10, help="Number of deployments to return.")
def deployments(workspace, service, limit):
    """List recent deployments for a service."""
    _output(_run(tools.deployments(workspace, service, limit)))


@main.command()
@click.argument("workspace")
@click.argument("service")
@click.argument("deployment_id")
def rollback(workspace, service, deployment_id):
    """Roll back a service to a specific deployment."""
    _output(_run(tools.rollback(workspace, service, deployment_id)))


@main.command("service-info")
@click.argument("workspace")
@click.argument("service")
def service_info(workspace, service):
    """Get detailed configuration for a Railway service."""
    _output(_run(tools.service_info(workspace, service)))


@main.command("http-logs")
@click.argument("workspace")
@click.argument("service")
@click.option("--deployment-id", default=None, help="Specific deployment ID.")
@click.option("--limit", default=50, help="Number of log entries.")
def http_logs(workspace, service, deployment_id, limit):
    """Get HTTP request logs for a service."""
    _output(_run(tools.http_logs(workspace, service, deployment_id, limit)))


@main.command("deployment-logs")
@click.argument("workspace")
@click.argument("deployment_id")
@click.option("--limit", default=100, help="Number of log lines to return.")
@click.option("--build", is_flag=True, help="Show build logs instead of deploy logs.")
@click.option("--filter", "filter_str", default=None, help="Filter log lines.")
def deployment_logs(workspace, deployment_id, limit, build, filter_str):
    """Get logs for a specific deployment by ID."""
    _output(
        _run(tools.deployment_logs(workspace, deployment_id, limit, build, filter_str))
    )


@main.command("unlink-repo")
@click.argument("workspace")
@click.argument("service")
def unlink_repo(workspace, service):
    """Disconnect a service from its linked GitHub repo."""
    _output(_run(tools.unlink_repo(workspace, service)))


@main.command()
@click.argument("workspace")
def doctor(workspace):
    """Audit a workspace for Railway deployment best practices."""
    _output(_run(tools.doctor(workspace)))


# ---------------------------------------------------------------------------
# MCP server command
# ---------------------------------------------------------------------------


@main.command()
def serve():
    """Start the MCP server (for Claude Code, Cursor, etc.)."""
    from railguey.mcp import mcp

    mcp.run()
