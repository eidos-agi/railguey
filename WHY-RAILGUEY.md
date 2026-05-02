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
| Ghost repo link | Env var operations blocked | March 2026 case study (below) |

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

## Case study: Ghost repo links block env var operations (March 2026)

This isn't hypothetical. It happened to us while building railguey itself.

### The situation

A Railway project with 8 services. Five had been connected to GitHub repos at some point via Railway's GitHub App integration. The GitHub App later lost access to the `greenmark-waste-solutions` org — possibly a permission change, possibly the app was reinstalled. Nobody noticed because deploys had already moved to token-based CI/CD.

### What broke

Setting a simple environment variable — `NEXT_PUBLIC_SUPABASE_URL` — via the Backboard GraphQL API (`variableUpsert` mutation):

```json
{
  "error": "GraphQL error",
  "details": [{
    "message": "Repository \"greenmark-waste-solutions/cerebro-qa\" not found or is not accessible"
  }]
}
```

**Setting an env var has nothing to do with GitHub.** But Railway's `variableUpsert` mutation validates the linked repo before writing the variable. If the GitHub App can't access the repo, the entire operation fails — even though the variable and the repo are completely unrelated.

### The damage

| What we tried | Result |
|---|---|
| `variableUpsert` via GraphQL | Blocked — "Repository not found" |
| `serviceDisconnect` via GraphQL (project token) | Blocked — "Bad Access" (requires account-level auth) |
| Introspect `ServiceSource` to see the link | `repo: null, image: null` — the ghost link is invisible to the API |

The repo link was:
- **Invisible** — `service_info` and `source` queries returned null
- **Unremovable** — project-scoped tokens can't call `serviceDisconnect`
- **Blocking unrelated operations** — env var writes, which have zero connection to GitHub

The only fix was logging into the Railway dashboard with account credentials and manually disconnecting each service's GitHub source. A project-scoped token — the thing designed for automation — couldn't fix it.

### The lesson

Railway's GitHub repo linking doesn't just affect deploys. It injects itself into the **env var pipeline**. A broken GitHub connection doesn't just stop your deploys from triggering — it stops you from configuring your services at all.

This is the strongest argument for never linking repos in the first place:

1. **Deploys work without it** — token-based CI/CD via GitHub Actions
2. **Env var operations work without it** — `variableUpsert` succeeds immediately on unlinked services
3. **The link creates invisible coupling** — it doesn't show up in API queries but blocks API mutations
4. **Recovery requires dashboard access** — project tokens can't clean up the mess

The three services that were never linked to GitHub repos (`cerebro`, `cerebro-warp-speed`, `vault-simple`) had zero issues. Same project, same token, same API call — the only difference was the ghost repo link.

### Epilogue: the Dockerfile build-time vars trap

After fixing the ghost links and setting `NEXT_PUBLIC_SUPABASE_URL` on all 8 services, cerebro's build still failed with the same `supabaseUrl is required` error. Why?

Railway sets env vars on the **runtime container**, but cerebro uses a multi-stage Dockerfile. The `RUN npm run build` step runs in an isolated build stage that doesn't receive Railway's env vars. Next.js inlines `NEXT_PUBLIC_*` vars at build time via string replacement — if they don't exist during `npm run build`, they're replaced with `undefined` in the bundle.

The fix was two lines in the Dockerfile:

```dockerfile
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
RUN npm run build
```

Railway automatically passes env vars as Docker build args when `ARG` declarations exist. Without them, the build stage is blind to Railway's configuration.

This is a general trap for any Dockerized Next.js app on Railway: **runtime env vars don't reach Docker build stages unless explicitly declared as ARG**. It compounds with the ghost repo link problem — you can't even set the vars until the links are cleared, and once you set them they still don't reach the build.

---

## What railguey does about it

railguey isn't just an alternative deploy wrapper — it's opinionated about how Railway deployments should work.

### `railguey doctor` — audit your setup

Checks every workspace for four best practices:

1. **RAILWAY_TOKEN in `.env.local`** — the foundation
2. **`.env.local` in `.gitignore`** — don't leak the token
3. **GitHub Actions deploy workflow** — token-based CI/CD, not repo linking
4. **No GitHub repo linking** — actively warns if services are linked

### `railguey unlink-repo` — fix it in one call

Disconnects a service from its linked GitHub repo via the Backboard GraphQL API (`serviceDisconnect` mutation). After unlinking, `railguey doctor` points you to the CI/CD workflow examples.

### Copy-paste CI/CD workflows

Three ready-to-use GitHub Actions workflows in [`examples/`](examples/):

| File | What it does |
|------|-------------|
| `deploy.yml` | Minimal push-to-main deploy |
| `deploy-with-tests.yml` | Run tests first, deploy on success |
| `deploy-multi-service.yml` | Matrix strategy for multi-service repos |

---

## When repo linking is fine

This document makes a strong case against repo linking, but context matters. Repo linking is genuinely convenient for:

- **Hobby projects and quick demos** where a missed deploy means refreshing a dashboard, not losing revenue
- **Solo projects with low deploy frequency** where the 5-minute GitHub Actions setup isn't worth it yet
- **Teams evaluating Railway** that want the fastest path from "git push" to "live" before committing to CI/CD

The incidents above affected production workloads at scale. If you're deploying a weekend project and Railway's integration hiccups for an hour, you probably won't notice. The case for project tokens gets stronger as the cost of a missed or broken deploy goes up — production services, client projects, anything where "it didn't deploy and nobody noticed" is a real problem.

## The bottom line

Railway's GitHub integration has a documented history of outages caused by architectural issues in how it handles GitHub OAuth tokens, webhooks, and API calls. The project-token pattern sidesteps all of it by using a static token and letting GitHub Actions handle the trigger.

railguey encodes this pattern into every tool. It's not a workaround — it's just how deploys should work.

For the deeper architectural argument — why this isn't just bugs but a design flaw — read **[WHY-NOT-RAILWAY-APP.md](WHY-NOT-RAILWAY-APP.md)**.
