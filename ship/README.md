# Ship Instructions — railguey

> How to safely get code from working directory to published on PyPI.

railguey is a Python CLI package published to PyPI. There's no running service to deploy — shipping means: test, commit, push, and optionally tag a release.

## Status

### Steps
1. `git status` — modified/untracked files
2. `git diff --stat` — summary of changes
3. `git log --oneline -5` — recent commits
4. `git fetch && git status` — behind/ahead of remote
5. Report: files changed, uncommitted work, sync status

## Build

### Steps
1. **Editable install**: `pip install -e ".[dev]"` — verify package installs cleanly
2. **Import check**: `python -c "from railguey import __version__; print(__version__)"` — catch import errors
3. **Entry point check**: `railguey --help` — verify console script starts
4. Report: pass/fail for each

## Preflight

All must pass before committing.

### Steps
1. **Unit tests**: `pytest tests/ --ignore=tests/test_integration.py -v` — all non-xfailed tests must pass
2. **Wheel build**: `python -m build` then inspect contents:
   - `python -c "import zipfile; z=zipfile.ZipFile('dist/railguey-*.whl'); [print(f) for f in sorted(z.namelist())]"`
   - HARD FAIL if `tests/`, docs, images, or any non-package file appears in the wheel
3. **Version check**: Verify `railguey/__init__.py` `__version__` matches `pyproject.toml` `version`
   - `python -c "from railguey import __version__; print(__version__)"` vs `grep '^version' pyproject.toml`
   - HARD FAIL if they differ
4. **Secrets scan**: Grep staged files for sensitive patterns
   - Pattern: `(api_key|secret|password|token|credential).*=.*['"][^'"]{8,}`
   - Also check for `.env` files, `credentials.json`, private keys
   - HARD FAIL if found (note: test files contain mock tokens like `test-token-123` — those are fine)
5. **Debug artifacts**: Check for `breakpoint()`, `import pdb`, `print(` outside of tests
   - WARNING only, not a blocker
6. Report: pass/fail for each

## Commit

### Steps
1. Run **Status** to see what's changed
2. Run **Preflight** — stop if any hard failures
3. Analyze changes — group by logical unit:
   - Package structure changes (moves, __init__.py, pyproject.toml) together
   - Test import updates together
   - CI workflows together
   - Docs (README, CHANGELOG, WHY-RAILGUEY) together
4. For each logical group:
   a. Stage the relevant files (specific files, not `git add .`)
   b. Write a commit message — imperative, < 72 chars, explains "why"
   c. Show the file list and message before creating
5. After all commits, show `git log --oneline -N`

### Commit message style
Match existing: short imperative descriptions. Look at `git log --oneline -10`.

## Push

### Steps
1. `git branch --show-current` — verify on expected branch
2. `git push` (or `git push -u origin <branch>` if no upstream)
3. Verify push succeeded
4. Check GitHub Actions: `gh run list --limit 3` — CI should trigger on push to main
5. Wait for CI to pass: `gh run watch` (optional, can skip if confident)

## Release

Tag a version and publish to PyPI via GitHub Actions.

### Pre-release checklist
1. All tests pass locally (ran in Preflight)
2. CI green on main (check after Push)
3. `CHANGELOG.md` has an entry for this version
4. Version in `pyproject.toml` and `railguey/__init__.py` match and are bumped

### Steps
1. `git tag -a v<VERSION> -m "v<VERSION> — <short description>"` — e.g. `v0.3.0 — CLI-only release`
2. `git push --tags`
3. Monitor: `gh run list --limit 3` — the publish workflow should trigger on the tag
4. After publish completes, verify on PyPI: `pip index versions railguey` or check https://pypi.org/project/railguey/
5. **Smoke test from clean env**: `uvx railguey` in a directory with `.env.local` — verify it starts and responds

### PyPI trusted publisher setup (one-time)
If this is the first release:
1. Register at https://pypi.org/manage/account/publishing/
   - Project: `railguey`, Owner: `eidos-agi`, Repo: `railguey`, Workflow: `publish.yml`, Environment: `pypi`
2. Create `pypi` environment in GitHub repo Settings → Environments

## Verify

Post-push verification.

### Steps
1. **CI status**: `gh run list --limit 1` — latest run should be green
2. **Remote import**: `pip install railguey && python -c "from railguey import __version__; print(__version__)"` — only after a release
3. **Entry point**: `uvx railguey` — starts without error (timeout after 2s is success)

## Rollback

### Steps
1. **Bad commit on main**: `git revert <sha>` → push → CI will re-run
2. **Bad PyPI release**: You can't unpublish from PyPI, but you can:
   a. Yank the version: `pip install twine && twine yank railguey <version>`
   b. Bump version, fix the issue, release again
3. **Bad tag**: `git tag -d v<VERSION> && git push --delete origin v<VERSION>` — only if the publish workflow hasn't run yet

## Ship All

Full pipeline: Status → Build → Preflight → Commit → Push.

Deploy and Release are intentional, manual steps — they don't auto-run.

### Steps
1. **Status** — what's changing?
2. **Build** — editable install, import check, entry point
3. **Preflight** — tests, wheel contents, version match, secrets scan
4. **Commit** — clean, grouped commits
5. **Push** — send to remote, verify CI triggers

Stop on any failure. After Push, suggest Release if this looks like a version bump.
