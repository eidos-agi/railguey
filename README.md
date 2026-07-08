# railguey

<p align="center">
  <img src="https://raw.githubusercontent.com/eidos-agi/railguey/main/logo.png" alt="railguey" width="500">
</p>

<p align="center">
  Project-scoped Railway CLI.<br>
  Reads <code>RAILWAY_TOKEN</code> from each project's <code>.env.local</code>, with no Railway account login or repo linking.
</p>

<p align="center">
  <a href="https://pypi.org/project/railguey/"><img src="https://img.shields.io/pypi/v/railguey" alt="PyPI"></a>
  <a href="https://github.com/eidos-agi/railguey/actions/workflows/ci.yml"><img src="https://github.com/eidos-agi/railguey/actions/workflows/ci.yml/badge.svg" alt="Tests"></a>
  <a href="https://pypi.org/project/railguey/"><img src="https://img.shields.io/pypi/pyversions/railguey" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/eidos-agi/railguey" alt="License"></a>
</p>

---

**railguey is for teams and businesses that need reliable Railway deployments.** It is not the simplest way to deploy — Railway's built-in GitHub app is simpler. But railguey is more reliable, because it draws a cleaner engineering boundary.

## Why not just use Railway's GitHub App?

Railway's GitHub App is fast to set up: connect your repo, push to main, and your service deploys. For prototyping, that speed is genuinely great. But speed of setup and quality of engineering are different things.

The GitHub App bundles five responsibilities into one opaque chain: watch for code changes, authenticate to GitHub, receive a webhook, clone the repo, build and deploy. When the chain works, it feels like magic. When it doesn't — and it has broken [four times in four months](WHY-RAILGUEY.md#the-incident-timeline) — there is no observability, no retry, and no notification. Your push goes in. Nothing comes out. You find out when a customer does.

```text
git push
   |
   v
GitHub webhook -> Railway GitHub App -> clone/build/deploy
   |                    |                     |
   +-- missed event     +-- auth drift        +-- silent trigger failure
```

Every decision diamond in this diagram is a place where the chain can silently break. Missed webhooks, lost build triggers, GitHub App auth failures — all produce the same result: **nothing happens, and nobody tells you**.

This isn't a bug. It's an architectural choice. Railway chose to own the entire pipeline from push to deploy, which means every failure in GitHub's webhook delivery becomes Railway's problem — and yours.

## How railguey fixes this

railguey separates concerns. GitHub Actions watches your repo (GitHub watching GitHub — the thing it was built for). railguey handles the deploy via Railway's API using project-scoped tokens. Railway builds and runs your service (the thing *it* was built for). Each system does one job.

```text
git push
   |
   v
GitHub Actions -> tests -> railguey -> Railway API -> build/deploy
       |             |        |              |
       +-- visible   +-- fail +-- nonzero    +-- deployment status
```

If CI fails, GitHub tells you. If the deploy fails, the CLI returns an error. If the service is unhealthy, `railguey doctor` catches it. Every step is observable, retryable, and owned by the system best suited to do it.

**Fast delivery and good engineering aren't opposites** — but Railway's GitHub App trades the second for the first. railguey gives you both.

| Doc | What it covers |
|-----|---------------|
| **[WHY-NOT-RAILWAY-APP.md](WHY-NOT-RAILWAY-APP.md)** | The architectural argument — why coupling CI/CD triggering with deployment is a design flaw, not just a bug |
| **[WHY-RAILGUEY.md](WHY-RAILGUEY.md)** | The evidence — four incidents, community reports, and what the project-token pattern does differently |
| **[WHY-RAILGUEY.md#case-study](WHY-RAILGUEY.md#case-study-ghost-repo-links-block-env-var-operations-march-2026)** | Real-world case study — ghost GitHub repo links silently blocked env var operations across 5 services |
| **[docs/railway-agent-ssh.md](docs/railway-agent-ssh.md)** | `railguey research` — asking Railway's own agent about Railway services over `ssh railway.new`: setup, persistent conversations, flags, troubleshooting |

## When to use railguey

- You manage Railway services from agents, local shells, or CI and want reliable deploys, rollbacks, and logs without `railway login`
- You run multiple Railway projects and want one auth pattern across local dev, CI/CD, and AI tooling
- Deploy reliability matters — production services, client projects, anything where a silently missed deploy costs you
- You're already using GitHub Actions and want Railway deploys in the same pipeline as your tests

## When NOT to use railguey

- **Quick demos and hobby projects.** Railway's GitHub app is genuinely convenient for push-and-forget deploys. If you're prototyping and don't care about deploy reliability, the built-in integration is fine.
- **You only deploy once in a while from the terminal.** If manual dashboard checks are fine, the Railway CLI with a project token is enough.
- **You're happy with the dashboard.** If you deploy once a week and check status manually, railguey adds complexity you don't need.

## Known limitations

- **All tools depend on Railway's Backboard GraphQL API**, which isn't officially documented. The schema could change without notice.
- **No Railway CLI required.** The core deploy tools use Railway's GraphQL/API surfaces with project-scoped tokens. The legacy CLI backend has been removed.
- **One token per project.** Project-scoped tokens can't query across projects. If you manage 10 projects, you need 10 `.env.local` files in 10 workspaces. This is by design (isolation), but it's more setup than a user-level login.

## Install

Requires Python 3.10+. No Railway CLI needed.

```bash
pip install railguey
```

Or run without installing:

```bash
uvx railguey --help
```

<details>
<summary>Install from source</summary>

```bash
git clone https://github.com/eidos-agi/railguey.git
cd railguey
pip install -e .
```

</details>

## CLI usage

`pip install railguey` gives you the `railguey` command with the core deploy and diagnostics tools as subcommands:

```bash
railguey status ~/repos/my-app
railguey logs ~/repos/my-app cerebro --lines 50
railguey deploy ~/repos/my-app web
railguey deployments ~/repos/my-app cerebro --limit 5
railguey doctor ~/repos/my-app
railguey variables ~/repos/my-app web
railguey service-info ~/repos/my-app cerebro
```

Every command takes a `workspace` path — the directory containing `.env.local` with `RAILWAY_TOKEN`.

## First deploy of a fresh service

A brand-new Railway service needs both a `serviceCreate` mutation (with `environmentId` so the per-env instance materializes) AND a source upload to be deployable. railguey collapses this to one verb:

```sh
railguey service-bootstrap /path/to/repo my-service
```

Under the hood: `serviceCreate` with the project-token's `environmentId` (Railway requires this), then a gzipped tarball of the workspace POSTed to `https://backboard.railway.com/project/{p}/environment/{e}/up?serviceId={s}` — both project-token-only, no GitHub-Railway link, no account-level auth.

The tarball respects `.gitignore`, `.dockerignore`, and `.railwayignore` (90% of `.gitignore` semantics — no negation, no nested `**`); `.git`, `node_modules`, `.venv`, and `*.cache` directories are always excluded. Hard-cap of 256MB; use `.railwayignore` to trim larger workspaces.

For subsequent deploys, use `railguey upload-source` (just upload — service already exists) or `railguey deploy` (redeploy from existing source).

## Commands

Core CLI commands, all token-based. No Railway CLI required.

| Command | What it does |
|------|-------------|
| `railguey status` | Project overview — all services, deploy status, domains |
| `railguey services` | List services with IDs |
| `railguey logs` | Fetch recent deploy or build logs (with optional filter) |
| `railguey deploy` | Trigger a deploy from linked source |
| `railguey redeploy` | Redeploy latest deployment (rebuilds from source) |
| `railguey restart` | Restart latest deployment (no rebuild, fast) |
| `railguey variables` | List env vars for a service |
| `railguey variable-set` | Set an env var (triggers redeploy) |
| `railguey domain` | Generate a railway.app domain or add a custom domain |
| `railguey environment-create` | Create a new environment (staging, preview, etc.) |
| `railguey deployments` | Deployment history with IDs, statuses, timestamps, rollback eligibility |
| `railguey rollback` | Roll back to a specific deployment |
| `railguey service-info` | Full service config — build/start commands, healthcheck, region, replicas |
| `railguey http-logs` | HTTP request logs — status codes, latency, paths |
| `railguey deployment-logs` | Logs for a specific deployment by ID (deploy or build, with filter) |
| `railguey unlink-repo` | Disconnect a service from GitHub repo linking |
| `railguey service-create` | Create a service bound to the project token's environment |
| `railguey upload-source` | Tarball workspace + POST to Railway `/up` — deploy via project token |
| `railguey service-bootstrap` | One-call first deploy: `service-create` + `upload-source` |
| `railguey service-delete` | Delete a service from the Railway project (irreversible) |
| `railguey bucket list` | List buckets deployed in the project token's environment |
| `railguey bucket create` | Create a bucket and deploy it to an environment region |
| `railguey bucket info` | Show bucket size/object-count details |
| `railguey bucket credentials` | Show or reset S3-compatible bucket credentials |
| `railguey bucket rename` | Rename a bucket display name |
| `railguey bucket delete` | Delete a bucket from the environment (requires `--yes`) |
| `railguey doctor` | Audit a workspace for deployment best practices |
| `railguey research` | Ask Railway's own agent a question via `ssh railway.new` — see [docs/railway-agent-ssh.md](docs/railway-agent-ssh.md) |

`railguey doctor` checks:
1. `RAILWAY_TOKEN` exists in `.env.local`
2. `.env.local` is in `.gitignore`
3. GitHub Actions deploy workflow exists with token-based CI/CD
4. No services linked to GitHub repos

Every command requires a `workspace` parameter — the absolute path to a project directory that has a `.env.local` (or `.env`) containing `RAILWAY_TOKEN`. The one exception is `railguey research`, which talks to Railway's public agent endpoint and needs no token (it does need `tmux` and [`emux`](https://github.com/eidos-agi/emux) on PATH).

## Example

**CLI:**
```bash
railguey logs ~/repos/my-app web --lines 50
```

**Python library:**
```python
from railguey.lib import tools
result = await tools.logs("/Users/you/repos/my-app", "web", lines=50)
```

Both paths read `/Users/you/repos/my-app/.env.local`, extract the token, resolve the Railway project/service, and fetch logs through Railway's API.

## The project-token pattern

Railway lets you create [project-scoped tokens](https://docs.railway.com/guides/cli#project-tokens) — API keys that authenticate to a single project without any user login. These tokens work the same way everywhere:

| Context | How the token is used |
|---------|----------------------|
| **Local dev** | `.env.local` — `railguey logs`, `railguey upload-source`, etc. |
| **Agents using railguey** | Call the CLI with a workspace path |
| **GitHub Actions CI/CD** | Repository secret → `RAILWAY_TOKEN` env var |
| **Any CI system** | Same — export the token, run `railguey upload-source` |

One mechanism. No OAuth. No repo linking. No webhook fragility.

<details>
<summary>GitHub Actions deploy workflow (copy-paste)</summary>

Add `RAILWAY_TOKEN` as a [repository secret](https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions), then:

```yaml
# .github/workflows/deploy.yml
name: Deploy to Railway

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install railguey
        run: pip install railguey

      - name: Deploy
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
        run: railguey upload-source "$GITHUB_WORKSPACE" "${{ vars.RAILWAY_SERVICE }}" --message "$GITHUB_SHA"
```

Set `RAILWAY_SERVICE` as a [repository variable](https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/store-information-in-variables). More examples in [`examples/`](examples/).

</details>

## Token discovery

1. Looks for `RAILWAY_TOKEN=` in `{workspace}/.env.local`
2. Falls back to `{workspace}/.env`
3. Raises a clear error if not found

Supports bare values, single-quoted, and double-quoted values.

## License

MIT
