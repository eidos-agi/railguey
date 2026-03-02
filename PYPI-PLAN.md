# Plan: Publish railguey to PyPI

## Prerequisites

### 1. PyPI account
- Register at https://pypi.org/account/register/ (use `daniel@rhea-impact.com`)
- Enable 2FA (required for new projects since 2024)
- Create an API token: Account Settings → API tokens → "Add API token"
  - Scope: "Entire account" for first publish, then lock to project after

### 2. TestPyPI account (optional but recommended)
- Register at https://test.pypi.org/account/register/
- Same 2FA + API token setup
- Dry-run publishes here first

## Steps

### Step 1: Verify package metadata
```bash
pip install check-wheel-contents twine
python -m build
check-wheel-contents dist/railguey-0.2.0-py3-none-any.whl
twine check dist/*
```

Confirm:
- `pyproject.toml` has all required fields (name, version, description, license, authors, urls)
- README.md renders correctly (twine check validates this)
- No test files or secrets in the wheel

### Step 2: Claim the name on TestPyPI
```bash
twine upload --repository testpypi dist/*
```

Then verify:
```bash
pip install --index-url https://test.pypi.org/simple/ railguey
railguey --version
railguey --help
railguey serve --help
```

### Step 3: Publish to PyPI
```bash
twine upload dist/*
```

Verify:
```bash
pip install railguey
railguey --version
uvx railguey --help
uvx railguey serve
```

### Step 4: Lock API token to project
- Go to PyPI → Account Settings → API tokens
- Delete the "Entire account" token
- Create a new token scoped to the `railguey` project only
- Store in GitHub repo secret as `PYPI_API_TOKEN`

### Step 5: Automate future releases (GitHub Actions)
Create `.github/workflows/publish.yml`:
```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  publish:
    runs-on: ubuntu-latest
    permissions:
      id-token: write  # trusted publishing
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install build
      - run: python -m build
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Even better: use PyPI's [Trusted Publishers](https://docs.pypi.org/trusted-publishers/) instead of API tokens. Link the GitHub repo to the PyPI project — no secrets to manage.

### Step 6: GitHub release workflow
1. Bump version in `pyproject.toml` and `railguey/__init__.py`
2. Update `CHANGELOG.md`
3. Commit: `git commit -m "release: v0.2.0"`
4. Tag: `git tag v0.2.0`
5. Push: `git push origin main --tags`
6. Create GitHub release from the tag → triggers publish workflow

## Checklist

- [ ] PyPI account created with 2FA
- [ ] `twine check` passes
- [ ] TestPyPI upload works
- [ ] `pip install railguey` from TestPyPI works
- [ ] PyPI upload works
- [ ] `uvx railguey --help` works (proves it's installable without pre-install)
- [ ] `uvx railguey serve` starts MCP server
- [ ] API token scoped to project only
- [ ] GitHub Actions publish workflow added
- [ ] Trusted Publishers configured (replaces API token)

## Version strategy

- `0.2.0` — current (lib extraction + CLI)
- `0.2.x` — patch releases (bug fixes)
- `0.3.0` — next feature release
- `1.0.0` — when API is stable and battle-tested across multiple teams
