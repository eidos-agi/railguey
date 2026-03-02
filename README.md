<p align="center">
  <img src="logo.png" alt="railguey" width="500">
</p>

<p align="center">
  Project-scoped Railway MCP server.<br>
  Reads <code>RAILWAY_TOKEN</code> from each project's <code>.env.local</code> — no <code>railway login</code> needed.
</p>

---

## Why

The official Railway MCP requires `railway login` (user-level OAuth). If you manage multiple projects across different orgs, each with its own project-scoped token in `.env.local`, the official MCP can't use them.

**railguey** fixes this: every tool takes a `workspace` path, reads the token from that project's `.env.local`, and injects it into Railway CLI calls. No login. No global state. Token-per-project, the way it should work.

## Install

Requires the [Railway CLI](https://docs.railway.com/guides/cli) and Python 3.10+.

```bash
git clone https://github.com/rhea-impact/railguey.git
cd railguey
pip install -e .
```

## Configure Claude Code

Add to `~/.claude.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "Railway": {
      "command": "python3",
      "args": ["/path/to/railguey/server.py"]
    }
  }
}
```

## Tools

| Tool | What it does |
|------|-------------|
| `railguey_status` | Show all services in the project |
| `railguey_logs` | Fetch recent logs (deploy or build) |
| `railguey_deploy` | Trigger a deploy (non-blocking) |
| `railguey_variables` | List env vars for a service |
| `railguey_variable_set` | Set an env var (triggers redeploy) |

Every tool requires a `workspace` parameter — the absolute path to a project directory that has a `.env.local` (or `.env`) containing `RAILWAY_TOKEN`.

## Example

```python
railguey_logs(workspace="/Users/you/repos/my-app", service="web", lines=50)
```

This reads `/Users/you/repos/my-app/.env.local`, extracts the token, and runs:

```bash
RAILWAY_TOKEN=<token> railway logs --service web --lines 50
```

## Token Discovery

1. Looks for `RAILWAY_TOKEN=` in `{workspace}/.env.local`
2. Falls back to `{workspace}/.env`
3. Raises a clear error if not found

Supports bare values, single-quoted, and double-quoted values.

## License

MIT
