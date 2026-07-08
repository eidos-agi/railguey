# Asking Railway's agent about your services over SSH (`railguey research`)

Railway ships its own AI agent behind a plain SSH endpoint: `ssh railway.new`
drops you into an interactive TUI where the agent answers questions about
deploys, cron schedules, logs, regions, pricing — anything covered by
Railway's product and docs. `railguey research` drives that agent
programmatically and returns its answer as JSON, so an AI agent (or a script)
can *read about* Railway services without a browser, a docs scrape, or a
support ticket.

```bash
railguey research "How do I add a cron schedule to a service?"
railguey research "and how do I see its logs?"     # follow-up — same conversation
railguey research "What regions can I deploy to?" --reset
```

## What it's for

- **Product questions**: "does Railway support X?", "what's the limit on Y?",
  "how do I configure Z?" — answered by the vendor's own agent from the
  official docs, not from a model's stale training data.
- **Agent workflows**: an AI agent operating Railway through railguey can fall
  back to `railguey research` when it hits a behavior it doesn't understand,
  ask the vendor, and act on the answer — all inside one CLI.

It is **not** for reading your project's live state. For that, use the
token-based verbs (`railguey status`, `logs`, `service-info`, `deployments`,
…) which hit Railway's API directly and return structured JSON.

## Prerequisites

Three binaries on `PATH`:

| Binary | Why | Install |
|---|---|---|
| `ssh` | Transport to `railway.new` | ships with the OS |
| `tmux` | Holds the persistent TUI session | `brew install tmux` |
| `emux` | Drives the TUI — model-picked navigation + settle-based Q&A | `uv tool install emux` |

Notably **not** required: `RAILWAY_TOKEN`. `railguey research` takes no
workspace argument — the `railway.new` endpoint is Railway's public agent, not
your project. (First connection uses `-o StrictHostKeyChecking=no` to accept
the host key.)

## How it works

1. On first call, a detached tmux session (`railguey-research`) runs
   `ssh railway.new`.
2. `emux navigate` steers through the TUI's menus to the free-text chat prompt
   ("Message the agent…"). Navigation is model-driven, so menu reordering or
   new screens don't break it.
3. `emux ask` types your question, waits for the streamed reply to settle
   (default: 3s of an unchanged pane, 90s hard cap), and returns the text.

The JSON result looks like:

```json
{
  "ok": true,
  "question": "How do I add a cron schedule to a service?",
  "answer": "…the agent's reply…",
  "via": "ssh railway.new",
  "session": "railguey-research",
  "new_conversation": true
}
```

On failure you get `{"error": "..."}` and a nonzero exit, same as every other
railguey verb.

## Conversation persistence

The chat session **persists across calls** — the tmux session stays alive, so
the agent keeps context and follow-ups work ("and for that service?").

| Flag | Effect |
|---|---|
| `--reset` | Kill any existing session and start a fresh conversation |
| `--close` | Answer, then tear the session down (default is to keep it open) |
| `--settle N` | Seconds the reply pane must be still before it counts as done (default 3) |
| `--max-seconds N` | Hard cap on waiting for a reply (default 90) |

Long or complex questions may stream slowly — raise `--settle`/`--max-seconds`
rather than assuming the agent hung.

## Troubleshooting

- **`emux not found on PATH`** — `uv tool install emux`.
- **`could not reach the Railway agent prompt`** — the error includes the last
  captured screen; the TUI may have changed or the connection failed. Inspect
  manually with `tmux attach -t railguey-research`, or `--reset` and retry.
- **`no answer from the Railway agent`** — usually a settle window shorter
  than the agent's think time; retry with `--settle 5 --max-seconds 180`.
- **Stale or weird context** — you're in an old conversation; `--reset`.

You can always skip railguey entirely and run `ssh railway.new` yourself for
an interactive session — `railguey research` exists so non-humans can do it.

## Not to be confused with `railway ssh`

The official Railway CLI's `railway ssh -s <service> -- <cmd>` is a different
thing: it executes a command **inside your running service container** (which
is also the only way to reach `*.railway.internal` mesh hostnames from
outside — there is no `-L`-style port-forward). Use that when you need to look
*inside* a running container; use `railguey research` when you need to ask
Railway *about* Railway. If you do reach for `railway ssh`, railguey's token
convention carries over: source `RAILWAY_TOKEN` from the workspace's
`.env.local` and no `railway login` is needed. One safety note applies in
both worlds: don't dump a service's whole environment (`printenv`) into a
transcript — read the one variable you need, or use it in place without
echoing it.
