# Plan: Publish railguey to PyPI

## Prerequisites

### 1. PyPI trusted publisher
- PyPI project: https://pypi.org/project/railguey/
- Publisher: GitHub Actions, `eidos-agi/railguey`, workflow `publish.yml`, environment `pypi`
- No PyPI API token is required for normal releases.

### 2. TestPyPI account (optional but recommended)
- Register at https://test.pypi.org/account/register/
- Same 2FA + API token setup
- Dry-run publishes here first

## Steps

### Step 1: Verify package metadata
```bash
pip install check-wheel-contents twine
python -m build
check-wheel-contents dist/railguey-*.whl
twine check dist/*
```

Confirm:
- `pyproject.toml` has all required fields (name, version, description, license, authors, urls)
- README.md renders correctly (twine check validates this)
- No test files or secrets in the wheel

### Step 2: Optional TestPyPI dry run
```bash
twine upload --repository testpypi dist/*
```

Then verify:
```bash
pip install --index-url https://test.pypi.org/simple/ railguey
railguey --version
railguey --help
```

### Step 3: Publish to PyPI
Publish by pushing a matching version tag. The `publish.yml` workflow validates that the tag and `pyproject.toml` version match, builds the package, and publishes via PyPI Trusted Publishing.

Verify:
```bash
pip install railguey==<version>
railguey --version
uvx railguey --help
```

### Step 4: GitHub release workflow
1. Bump version in `pyproject.toml` and `railguey/__init__.py`
2. Update `CHANGELOG.md`
3. Commit: `git commit -m "release: v<VERSION>"`
4. Tag: `git tag v<VERSION>`
5. Push: `git push origin main && git push origin v<VERSION>`
6. Confirm the Publish to PyPI workflow succeeds

## Checklist

- [x] PyPI trusted publisher configured
- [ ] `twine check` passes
- [ ] TestPyPI upload works, if using the optional dry run
- [ ] PyPI upload works
- [ ] `uvx railguey --help` works (proves it's installable without pre-install)
- [ ] `uvx railguey --help` shows the CLI command list
- [x] GitHub Actions publish workflow added

## Version strategy

- `0.3.x` — current CLI-only line
- `0.4.0` — next feature release
- `1.0.0` — when API is stable and battle-tested across multiple teams
