"""CLI interface — Click commands that delegate to railguey.lib.tools.

Usage:
    railguey status /path/to/workspace
    railguey logs /path/to/workspace cerebro --lines 50
"""

import asyncio
import json
import sys

import click

from railguey import __version__
from railguey.lib import tools


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _output(result: dict):
    """Pretty-print a tool result as JSON, exit non-zero if it carries an error.

    The "error" key is railguey's convention for tool-call failure (HTTP non-2xx,
    GraphQL errors, missing credentials, etc.). Without this exit-non-zero
    behavior, CI workflows that pipe `railguey <verb>` to a step succeed even
    when Railway returned a 404 — silently masking failed deploys.
    Caught 2026-05-02 when GHA showed green for an `upload-source` that 404'd.
    """
    click.echo(json.dumps(result, indent=2))
    if isinstance(result, dict) and "error" in result:
        sys.exit(1)


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


@main.command("service-create")
@click.argument("workspace")
@click.argument("name")
def service_create(workspace, name):
    """Create a new service bound to the project token's environment.

    The service is created with an instance ready for first deploy. Use
    `railguey upload-source` (or one-call `railguey service-bootstrap`) to
    push code and trigger the first build.
    """
    _output(_run(tools.service_create(workspace, name)))


@main.command("upload-source")
@click.argument("workspace")
@click.argument("service")
@click.option("--message", default=None, help="Optional deploy message.")
def upload_source(workspace, service, message):
    """Tarball workspace + POST to Railway /up — trigger a deploy via project token."""
    _output(_run(tools.upload_source(workspace, service, message)))


@main.command("service-bootstrap")
@click.argument("workspace")
@click.argument("name")
@click.option("--message", default=None, help="Optional deploy message.")
def service_bootstrap(workspace, name, message):
    """Create service (if absent) AND upload first source — one-call first deploy."""
    _output(_run(tools.service_bootstrap(workspace, name, message)))


@main.command("service-delete")
@click.argument("workspace")
@click.argument("service")
def service_delete(workspace, service):
    """Delete a service from the Railway project. Irreversible."""
    _output(_run(tools.service_delete(workspace, service)))


@main.command("volume-create")
@click.argument("workspace")
@click.argument("service")
@click.argument("mount_path")
def volume_create(workspace, service, mount_path):
    """Create a Railway volume and attach it to a service at MOUNT_PATH.

    Project-token-only. Default size is 50 GB. Service redeploys
    automatically once the volume is attached.
    """
    _output(_run(tools.volume_create(workspace, service, mount_path)))


@main.command()
@click.argument("workspace")
def volumes(workspace):
    """List all volumes in the Railway project with their mount state."""
    _output(_run(tools.volumes(workspace)))


@main.command("volume-delete")
@click.argument("workspace")
@click.argument("volume_id")
def volume_delete(workspace, volume_id):
    """Delete a Railway volume. Irreversible — all data on the volume is lost."""
    _output(_run(tools.volume_delete(workspace, volume_id)))


@main.command("volume-resize")
@click.argument("workspace")
@click.argument("volume_instance_id")
@click.argument("size_mb", type=int)
def volume_resize(workspace, volume_instance_id, size_mb):
    """Resize a volume instance to SIZE_MB megabytes. Grow-only — Railway
    rejects shrink. Get VOLUME_INSTANCE_ID from `railguey volumes`."""
    _output(_run(tools.volume_resize(workspace, volume_instance_id, size_mb)))


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


@main.group()
def bucket():
    """Manage Railway storage buckets."""


@bucket.command("list")
@click.argument("workspace")
def bucket_list(workspace):
    """List buckets deployed in the project token's environment."""
    _output(_run(tools.buckets(workspace)))


@bucket.command("create")
@click.argument("workspace")
@click.argument("name", required=False)
@click.option(
    "--region",
    default="sjc",
    type=click.Choice(["sjc", "iad", "ams", "sin"]),
    help="Bucket region.",
)
def bucket_create(workspace, name, region):
    """Create a bucket and deploy it to the project token's environment."""
    _output(_run(tools.bucket_create(workspace, name, region)))


@bucket.command("info")
@click.argument("workspace")
@click.argument("bucket_name")
def bucket_info(workspace, bucket_name):
    """Show bucket details."""
    _output(_run(tools.bucket_info(workspace, bucket_name)))


@bucket.command("credentials")
@click.argument("workspace")
@click.argument("bucket_name")
@click.option("--reset", is_flag=True, help="Reset S3 credentials before returning them.")
@click.option("--yes", is_flag=True, help="Confirm credential reset.")
def bucket_credentials(workspace, bucket_name, reset, yes):
    """Show or reset S3-compatible bucket credentials."""
    if reset and not yes:
        _output({"error": "Credential reset requires --yes."})
    _output(_run(tools.bucket_credentials(workspace, bucket_name, reset)))


@bucket.command("rename")
@click.argument("workspace")
@click.argument("bucket_name")
@click.argument("name")
def bucket_rename(workspace, bucket_name, name):
    """Rename a bucket display name."""
    _output(_run(tools.bucket_rename(workspace, bucket_name, name)))


@bucket.command("delete")
@click.argument("workspace")
@click.argument("bucket_name")
@click.option("--yes", is_flag=True, help="Confirm bucket deletion.")
def bucket_delete(workspace, bucket_name, yes):
    """Delete a bucket from the project token's environment."""
    if not yes:
        _output({"error": "Bucket deletion requires --yes."})
    _output(_run(tools.bucket_delete(workspace, bucket_name)))
