# Why railguey exists

Railway is a great platform. Its GitHub integration is not.

Between November 2025 and February 2026, Railway published **four incident reports** — three of which directly involved the GitHub integration or deployment pipeline. Community forums tell the rest of the story: deploys silently not triggering, infinite redirect loops during auth, repos not loading.

railguey exists because we got tired of debugging Railway's webhook chain at 2am. Project-scoped tokens bypass all of it.

---

## The incident timeline

### Nov 20, 2025 — Legitimate deployments killed

A misconfigured automated enforcement system incorrectly terminated legitimate user deployments. All deployments on Railway were temporarily delayed due to a deployment task queue issue.

Source: [Incident Report: November 20th, 2025](https://blog.railway.com/p/incident-report-november-20-2025)

### Nov 25, 2025 — GitHub API cascade failure

GitHub API calls slowed to nearly 4x their usual p95 latency during peak deployment hours. This caused a cascading backlog in Railway's task queue. Workers handling GitHub API calls consumed elevated resources and began OOM-crashing, which intensified system pressure and caused remaining workers to crash too.

Source: [Incident Report: November 25th, 2025](https://blog.railway.com/p/incident-report-november-25-2025)

### Jan 28–29, 2026 — GitHub OAuth rate limit (the big one)

Railway hit GitHub's OAuth token rate limit of 2,000 tokens per hour. Users couldn't log in via GitHub. Deploys failed with "GitHub repo not found" errors during peak US business hours.

**Root cause:** Railway's dataloader for creating GitHub installation access tokens was not caching tokens across requests, burning ~82 new tokens per second at peak. The fix reduced token creation by over 90% — meaning the system had been wasting 90% of its GitHub API budget since inception.

Railway's post-mortem listed six remediation items including caching installation tokens, consolidating deployment status updates, switching to installation tokens, optimizing repository access checks, and moving automatic repo sync to manual.

Source: [Incident Report: January 28-29, 2026](https://blog.railway.com/p/incident-report-january-26-2026)

### Feb 11, 2026 — Anti-fraud false positive

A misconfigured automated abuse enforcement system incorrectly terminated legitimate user deployments after a new anti-fraud ruleset delivered false positives for legitimate workloads. Roughly 3% of all Railway workloads were taken offline — applications and databases received erroneous SIGTERM signals.

Source: [Incident Report: February 11, 2026](https://blog.railway.com/p/incident-report-february-11-2026)

### Community reports (ongoing)

- ["URGENT: GitHub deploys not triggering for any projects"](https://station.railway.com/questions/urgent-git-hub-deploys-not-triggering-fo-d093d9e8)
- ["Github integration issue" — infinite redirect loops](https://station.railway.com/questions/github-integration-issue-ae8a95ee)
- ["Deploy from GitHub repo not loading repos"](https://station.railway.com/questions/deploy-from-git-hub-repo-not-loading-repo-4e397ea6)
- ["No longer able to deploy GitHub repos"](https://station.railway.com/questions/no-longer-able-to-deploy-git-hub-repos-8f2924ac)

---

## What goes wrong with GitHub repo linking

When you link a Railway service to a GitHub repo, the deploy chain looks like this:

```
git push → GitHub webhook → Railway ingests webhook → Railway fetches repo
         → Railway creates OAuth token → Railway clones → Railway builds → Railway deploys
```

Every arrow is a failure point:

| Failure point | What happens | Incident example |
|---|---|---|
| GitHub webhook delivery | Deploy silently doesn't trigger | Community reports (ongoing) |
| Railway webhook ingestion | Task queue backs up | Nov 25, 2025 |
| OAuth token creation | Rate limited by GitHub | Jan 28–29, 2026 |
| GitHub API latency | Cascade failure, OOM crashes | Nov 25, 2025 |
| Railway enforcement system | Legitimate deploys killed | Nov 20, 2025; Feb 11, 2026 |

That's five links in a chain, and four of them have broken publicly in the last four months.

---

## What the project-token pattern does differently

```
git push → GitHub Actions → `railway up` with RAILWAY_TOKEN → Railway builds → Railway deploys
```

Two arrows instead of five. GitHub Actions handles the webhook (its own infrastructure, not Railway's). The `railway up` command authenticates with a project-scoped token — no OAuth, no rate limits, no webhook chain.

| Failure point | Repo linking | Token-based CI/CD |
|---|---|---|
| GitHub webhook delivery | Railway must receive it | GitHub Actions receives it (native) |
| OAuth token creation | Railway creates per-deploy | None — project token is static |
| GitHub API rate limits | Railway burns tokens at ~82/sec | None — no GitHub API calls |
| Railway enforcement bugs | Can kill linked deploys | `railway up` is a direct API call |
| Debugging | Toggle integration off/on in dashboard | Read GitHub Actions logs |

The project-token pattern doesn't just avoid Railway's GitHub integration bugs — it eliminates the entire class of failure. There's no webhook to miss, no OAuth token to rate-limit, no GitHub API to slow down.

---

## What railguey does about it

railguey isn't just an alternative MCP server — it's opinionated about how Railway deployments should work.

### `railguey_doctor` — audit your setup

Checks every workspace for four best practices:

1. **RAILWAY_TOKEN in `.env.local`** — the foundation
2. **`.env.local` in `.gitignore`** — don't leak the token
3. **GitHub Actions deploy workflow** — token-based CI/CD, not repo linking
4. **No GitHub repo linking** — actively warns if services are linked

### `railguey_unlink_repo` — fix it in one call

Disconnects a service from its linked GitHub repo via the Backboard GraphQL API (`serviceDisconnect` mutation). After unlinking, `railguey_doctor` points you to the CI/CD workflow examples.

### Copy-paste CI/CD workflows

Three ready-to-use GitHub Actions workflows in [`examples/`](examples/):

| File | What it does |
|------|-------------|
| `deploy.yml` | Minimal push-to-main deploy |
| `deploy-with-tests.yml` | Run tests first, deploy on success |
| `deploy-multi-service.yml` | Matrix strategy for multi-service repos |

---

## The bottom line

Railway's GitHub integration has a documented history of outages caused by architectural issues in how it handles GitHub OAuth tokens, webhooks, and API calls. The project-token pattern sidesteps all of it by using a static token and letting GitHub Actions handle the trigger.

railguey encodes this pattern into every tool. It's not a workaround — it's just how deploys should work.
