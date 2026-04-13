# Changelog

## v0.2.6 — Doctor checks account system + PyPI fix

- **Fixed**: CHANGELOG headers now use `v` prefix to match publish workflow validation
- **Improved**: Doctor now checks if the account system covers multi-environment gaps. When accounts are registered for uncovered environments, the token scope check passes instead of failing.
- **Improved**: Remediation suggests `railguey_account_add` + `railguey_account_default` instead of "generate broader token"

## v0.2.5 — Account system wired into token resolution

- **Fixed**: `_load_token()` now checks the account system (`~/.railguey/accounts.json`) before falling back to `.env.local`. Previously, `railguey_account_add` and `railguey_account_default` had no effect on actual API calls — every tool still read from `.env.local`.
- **Behavior change**: When a default account is set, its token takes priority over the workspace `.env.local` token. This lets `railguey_account_default production` switch all tools to the production environment without swapping `.env` files.
- **Use case**: Multi-environment workflows (e.g., setting a Railway variable on production from a workspace that defaults to develop).

## 0.2.4 — PyPI README fix + org migration

- **Fixed**: README images now use absolute URLs (PyPI renders from sdist, relative paths broke)
- **Fixed**: All references migrated from `rhea-impact` to `eidos-agi`
- **Fixed**: LICENSE copyright updated to Eidos AGI
- **Fixed**: Author email updated to daniel@eidosagi.com
- **Fixed**: Publish workflow permissions (contents:read for private repos)

## 0.2.3 — First PyPI publish

- First publish to PyPI under `eidos-agi` org
- Trusted publisher configured (OIDC, no API tokens)

## 0.2.0 — First PyPI release

- **Package restructure**: proper Python package (`railguey/` directory) instead of bare `server.py`
- **Entry point**: `pip install railguey` then run `railguey` or use `uvx railguey`
- **CI**: GitHub Actions test matrix (Python 3.10–3.13) and PyPI publish on tag
- **Wheel fix**: `packages = ["railguey"]` — tests and docs no longer leak into the wheel

No tool changes. All 17 tools work exactly as before.

## 0.1.0 — Initial development

- 17 MCP tools: 10 CLI-backed, 5 GraphQL-backed, 1 coaching, 1 audit
- Dual backend: Railway CLI + Backboard GraphQL API
- Project-scoped token discovery from `.env.local`
- `railguey_doctor` workspace audit (4-point check)
- 39 unit tests + 38 integration tests
