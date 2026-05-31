---
name: use-railguey
description: Use when deploying, diagnosing, adding domains, reading logs, or proving Railway service state through the railguey CLI. Prefer this over the Railway CLI for project-token workflows.
---

# Use Railguey

Use this skill when Codex needs to operate Railway through the `railguey` CLI.

Railguey is not the Railway CLI. It is the Eidos project-scoped Railway control surface. It reads `RAILWAY_TOKEN` from the target workspace, usually `.env.local`, and talks to Railway through project-token APIs.

## Core Rules

- Use `railguey`, not `railway`, unless the user explicitly asks for Railway CLI behavior.
- Always pass the target workspace path as the first positional argument when the command requires it.
- Treat the workspace `.env.local` as the authority surface for `RAILWAY_TOKEN`.
- Do not print token values. If a command might expose secrets, summarize structure only.
- Before deploying, run a local build/test command if the repo has a clear one.
- After deploying, prove the deployed state with `railguey deployments`, logs/status, and live HTTP smoke checks where the service exposes a URL.

## First Checks

From the repo being shipped:

```bash
railguey doctor /path/to/workspace
railguey status /path/to/workspace
railguey services /path/to/workspace
```

If `doctor` reports missing `RAILWAY_TOKEN`, stop and ask for the project token setup path. Do not switch to account-level `railway login` as a workaround.

## Shipping Flow

Use this for a repo that already has a Railway service:

```bash
railguey doctor /path/to/workspace
railguey upload-source /path/to/workspace <service-name>
railguey deployments /path/to/workspace <service-name> --limit 5
railguey logs /path/to/workspace <service-name> --lines 100
```

Use this for a fresh service:

```bash
railguey service-bootstrap /path/to/workspace <service-name>
railguey deployments /path/to/workspace <service-name> --limit 5
```

Use `railguey deploy` only when the service is intentionally redeploying existing source. Prefer `upload-source` when shipping the current local repo contents.

## Domain Flow

To add a custom domain:

```bash
railguey domain /path/to/workspace <service-name> <domain>
```

Capture the DNS target returned by Railway. DNS still has to be created in the domain provider. Railguey can prove Railway accepted the custom domain; it cannot prove DNS exists until public DNS resolves.

## Evidence Standard

A shipping report should include:

- Workspace path.
- Service name.
- Command used for deploy.
- Deployment ID or latest deployment row.
- Deployment status.
- Relevant log excerpt summary.
- Public URL smoke result, including status code and marker.
- Any DNS or domain validation gaps.

## Common Commands

```bash
railguey service-info /path/to/workspace <service-name>
railguey variables /path/to/workspace <service-name>
railguey http-logs /path/to/workspace <service-name> --limit 25
railguey deployment-logs /path/to/workspace <deployment-id> --lines 100
railguey rollback /path/to/workspace <service-name> <deployment-id>
```

Use destructive operations such as `service-delete`, bucket deletion, rollback, or variable changes only when the user explicitly asks for that exact action in the current turn.
