# Changelog

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
