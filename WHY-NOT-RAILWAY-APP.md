# Why not the Railway GitHub app?

The Railway GitHub app is a monolith in disguise.

One system handles webhook reception, OAuth token lifecycle, repo cloning, build orchestration, and deployment. When any link fails, the whole chain fails — and the failure mode is silence. Your deploy just doesn't happen, and nobody tells you.

This isn't a bug. It's a design flaw.

---

## The architectural argument

A deployment platform shouldn't also be a CI/CD trigger. Those are different jobs with different failure domains:

| Job | Failure domain | Who should own it |
|-----|---------------|-------------------|
| Watch for code changes | GitHub API availability, webhook delivery | GitHub |
| Authenticate to the repo | OAuth token lifecycle, rate limits | GitHub |
| Decide whether to deploy | Test results, branch rules, approvals | Your CI (GitHub Actions, etc.) |
| Build the app | Dockerfile, dependencies, build cache | Railway |
| Deploy the app | Container orchestration, health checks, routing | Railway |

Railway's GitHub integration couples all five. A GitHub API rate limit can take down your deploy pipeline. An OAuth token cache miss can prevent a build. A webhook delivery failure can silently skip a release.

The project-token pattern draws the boundary where it belongs:

```
GitHub Actions: watch → authenticate → decide → trigger
Railway:        build → deploy
```

Two systems. Two failure domains. A GitHub outage affects your CI but not your ability to manually deploy. A Railway outage affects your deploys but not your ability to run tests and know your code is ready.

## The evidence says the same thing

Between November 2025 and February 2026, Railway published [four incident reports](WHY-RAILGUEY.md#the-incident-timeline). Three trace directly to the watching-and-authenticating steps — not the building-and-deploying steps:

| Incident | Root cause | Which job failed? |
|----------|-----------|-------------------|
| Nov 25, 2025 | GitHub API latency caused cascade OOM | Authenticating / cloning |
| Jan 28–29, 2026 | 82 OAuth tokens/sec, no caching | Authenticating |
| Community reports | Deploys silently not triggering | Watching (webhook) |

Railway fixed the 82-tokens/second bug by adding caching. But the structural problem remains: they're operating a GitHub API client at scale as a side effect of being a deployment platform. The next incident will be a different symptom of the same architecture.

## The counterargument

"Railway will fix these bugs eventually."

Maybe. But even a perfectly executed version of this architecture is fragile by construction. You've coupled two independent failure domains into one chain. Every link you add between "git push" and "container running" is a link that can break silently. The question isn't whether Railway's engineering team is competent — it's whether a deployment platform should be in the business of managing GitHub OAuth tokens at all.

## What this means in practice

If you use Railway's GitHub app:
- A GitHub API slowdown can delay or prevent your deploy
- A Railway enforcement bug can kill deploys that were building fine
- A webhook delivery failure means your deploy silently doesn't happen
- Debugging requires checking Railway's dashboard, not your own CI logs
- You have no pre-deploy gate — no tests run before Railway starts building

If you use project tokens + GitHub Actions:
- GitHub watches GitHub (native, no external auth)
- You run tests before deploying (pre-deploy gate)
- Railway receives a `railway up` call with a static token (no OAuth, no webhook)
- Failures show up in GitHub Actions logs, where you already look
- You can deploy manually with the same token if GitHub Actions is down

The second pattern has fewer moving parts, cleaner failure boundaries, and better observability. It's more setup than clicking "connect repo" in a dashboard. That's the tradeoff, and for anything beyond hobby projects, it's worth it.

---

See also: **[WHY-RAILGUEY.md](WHY-RAILGUEY.md)** for the full incident timeline and community reports.
