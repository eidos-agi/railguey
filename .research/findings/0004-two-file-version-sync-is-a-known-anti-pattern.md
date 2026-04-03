---
id: '0004'
title: 'Two-file version sync is a known anti-pattern'
status: open
evidence: CONFIRMED
sources:
- text: 'https://packaging.python.org/en/latest/guides/writing-pyproject-toml/ (content_hash:pypaguide)'
  tier: PRIMARY
- text: 'Direct experience: ai-cockpit v0.2.0 required manual edits in 2 files, flagged
    as a loss function (L5) for version drift'
  tier: PRIMARY
disconfirmation: 'Searched for arguments in favor of hardcoded __version__. Some advocate
  for it when package may be used without installation (running from source). Mitigated
  by fallback: except PackageNotFoundError: __version__ = ''dev'''
created: '2026-04-03'
---

## Claim

Maintaining version in both pyproject.toml and __init__.py causes sync errors. The standard fix is importlib.metadata.version() which reads from installed package metadata at runtime, making pyproject.toml the single source of truth.

## Supporting Evidence

> **Source [PRIMARY]:** https://packaging.python.org/en/latest/guides/writing-pyproject-toml/ (content_hash:pypaguide), retrieved 2026-04-03
>
> **Source [PRIMARY]:** Direct experience: ai-cockpit v0.2.0 required manual edits in 2 files, flagged as a loss function (L5) for version drift, retrieved 2026-04-03

## Disconfirmation Search

Searched for arguments in favor of hardcoded __version__. Some advocate for it when package may be used without installation (running from source). Mitigated by fallback: except PackageNotFoundError: __version__ = 'dev'

## Caveats

None identified yet.
