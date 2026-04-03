---
id: TASK-0001
title: Fix version single-source-of-truth across all Eidos PyPI packages
status: To Do
created: '2026-04-03'
priority: high
tags:
  - phase-1
  - pypi
  - adr-001
definition-of-done:
  - Version defined in pyproject.toml only — no __version__ = string in __init__.py
  - importlib.metadata.version() used with PackageNotFoundError fallback
  - Applied to all 6+ Eidos PyPI packages
  - cockpit grade L5 (stale PyPI) still works
---
Replace hardcoded __version__ in __init__.py with importlib.metadata.version() across: ai-cockpit, eidos-mail, railguey, resume-resume, claude-session-commons, apple-a-day. Add PackageNotFoundError fallback for dev use.
